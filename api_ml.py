# api_ml.py

import json
import logging
import requests
import aiohttp
import asyncio
from sqlalchemy.orm import Session
from crud.utils import buscar_item_cache_por_sku, enriquecer_items_ws
from ws.items import obtener_todos_los_items, parsear_items
from database.models import MLPedidoCache, WsItem, MLItem
from datetime import datetime, timedelta, timezone
from crud.pedidos import guardar_pedido_en_cache



# Configuración
TOKEN_FILE    = "ml_token.json"
CLIENT_ID     = "5569606371936049"
CLIENT_SECRET = "wH7UDWXbA92DVlYa4P50cHBCLrEloMa0"
API_BASE      = "https://api.mercadolibre.com"

# Logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_valid_token():
    """
    Lee el archivo ml_token.json, verifica expiración y refresca si es necesario.
    """
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("ml_token.json inválido o no existe: %s", e)
        return None

    token      = data.get("access_token")
    created    = datetime.fromisoformat(data["created_at"])
    expires_in = data.get("expires_in", 0)

    # Si expiró (o está por expirar en menos de 60s), refrescamos:
    if datetime.now() >= created + timedelta(seconds=expires_in - 60):
        logger.debug("Token expirado o cercano a expirar, solicitando refresh...")
        r = requests.post(f"{API_BASE}/oauth/token", data={
            "grant_type":    "refresh_token",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": data.get("refresh_token")
        })
        r.raise_for_status()
        new = r.json()
        new["created_at"] = datetime.now().isoformat()
        with open(TOKEN_FILE, "w", encoding="utf-8") as f2:
            json.dump(new, f2, indent=2)
        return new.get("access_token")

    return token


def fetch_api(path, params=None, extra_headers=None):
    """
    GET genérico a api.mercadolibre.com con manejo de token.
    """
    token = get_valid_token()
    if not token:
        raise RuntimeError("No hay token válido para llamar a la API de Mercado Libre")
    headers = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)

    url = f"{API_BASE}{path}"
    logger.debug("→ Llamando a ML API: GET %s  headers=%s  params=%s", url, headers, params)
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()




async def get_order_details(order_id: str = None, shipment_id: str = None, db: Session = None) -> dict:
    
    token = get_valid_token()
    if not token:
        logger.error("No se obtuvo token válido")
        return {"cliente": "Error", "items": [], "primer_order_id": None}

    headers = {"Authorization": f"Bearer {token}"}
    TTL_MINUTOS = 10

    # 1️⃣ BUSCAR EN CACHE
    if db and shipment_id:
        cache = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).first()
        if cache:
            if cache.fecha_consulta and datetime.now(timezone.utc) - cache.fecha_consulta < timedelta(minutes=TTL_MINUTOS):
                logger.info("Se usó cache fresca para shipment_id=%s", shipment_id)
                return {
                    "cliente": cache.cliente,
                    "items": cache.detalle,
                    "estado_envio": cache.estado_envio,
                    "estado_ml": cache.estado_ml,
                    "primer_order_id": cache.order_id,
                    "primer_shipment_id": cache.shipment_id,
                }
            else:
                logger.info("Cache expirada para shipment_id=%s, se consultará la API", shipment_id)

    # 2️⃣ ORDER_ID DIRECTO
    if order_id:
        try:
            od = fetch_api(f"/orders/{order_id}", extra_headers=headers)
            od["id"] = order_id  # asegurarse que tenga "id"
            await guardar_pedido_en_cache(od, db)
            parsed = parse_order_data(od)
            parsed["primer_order_id"] = order_id
            return parsed
        except Exception as e:
            logger.warning("/orders/%s devolvió error: %s", order_id, e)

    # 3️⃣ SHIPMENT_ID FLUJO COMPLETO
    if shipment_id:
        try:
            shipment_items = fetch_api(
                f"/shipments/{shipment_id}/items",
                extra_headers={**headers, "x-format-new": "true"}
            )

            try:
                shipment_data = fetch_api(f"/shipments/{shipment_id}", extra_headers=headers)
                shipment_status = shipment_data.get("status", "desconocido")
            except Exception as e:
                logger.warning("No se pudo obtener el estado del envío: %s", e)
                shipment_status = "desconocido"

            estado_traducido = {
                "pending": "Pendiente",
                "ready_to_ship": "Listo para armar",
                "shipped": "Enviado",
                "delivered": "Entregado",
                "not_delivered": "No entregado",
                "cancelled": "Cancelado",
                "returned": "Devuelto"
            }
            estado_envio = estado_traducido.get(shipment_status, shipment_status.capitalize())

            if not isinstance(shipment_items, list) or not shipment_items:
                logger.error("No hay shipping_items para shipment_id=%s", shipment_id)
                return {"cliente": "Error", "items": [], "primer_order_id": None, "shipment_status": shipment_status}

            all_items = []
            cliente = None
            primer_oid = None

            for entry in shipment_items:
                oid = entry.get("order_id")
                if not oid:
                    continue
                if primer_oid is None:
                    primer_oid = oid

                try:
                    od = fetch_api(f"/orders/{oid}", extra_headers=headers)
                except Exception as e:
                    logger.warning("/orders/%s devolvió error: %s", oid, e)
                    continue

                if cliente is None:
                    cliente = od.get("buyer", {}).get("nickname", "Cliente desconocido")

                for oi in od.get("order_items", []):
                    prod = oi.get("item", oi)
                    if prod.get("id") == entry.get("item_id") and prod.get("variation_id") == entry.get("variation_id"):
                        temp_order = {
                            "buyer": od.get("buyer", {}),
                            "order_items": [oi]
                        }
                        detalle_unico = parse_order_data(temp_order)
                        if detalle_unico.get("items"):
                            all_items.extend(detalle_unico["items"])
                        break

            # 🔁 Agregamos permalinks en paralelo
            await enriquecer_permalinks(all_items, token, db)
            # 🔁 Enriquecer en paralelo (si querés):
            await enriquecer_items_ws(all_items, db)


            if all_items:
                resultado = {
                    "cliente": cliente or "Cliente desconocido",
                    "items": all_items,
                    "primer_order_id": primer_oid,
                    "primer_shipment_id": shipment_id,
                    "estado_ml": shipment_status,
                    "estado_envio": estado_envio,
                }

                if db:
                    nuevo = MLPedidoCache(
                        shipment_id=shipment_id,
                        order_id=primer_oid,
                        cliente=cliente,
                        estado_envio=estado_envio,
                        estado_ml=shipment_status,
                        detalle=all_items
                    )
                    db.merge(nuevo)
                    db.commit()

                return resultado

            logger.error("No se obtuvieron ítems tras procesar shipment_id=%s", shipment_id)

        except Exception as e:
            logger.warning("Error procesando /shipments/%s/items: %s", shipment_id, e)

    logger.error("No se encontró order ni shipment válido (order_id=%s, shipment_id=%s)", order_id, shipment_id)
    return {"cliente": "Error", "items": [], "primer_order_id": None}



