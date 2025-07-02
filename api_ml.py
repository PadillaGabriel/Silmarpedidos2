# api_ml.py

import json
import logging
import requests
import aiohttp
import asyncio
from sqlalchemy.orm import Session
from crud.pedidos import buscar_item_cache_por_sku 
from database.models import WsItem
from database.models import MLPedidoCache
from datetime import datetime, timedelta

# Configuración
TOKEN_FILE    = "ml_token.json"
CLIENT_ID     = "5569606371936049"
CLIENT_SECRET = "wH7UDWXbA92DVlYa4P50cHBCLrEloMa0"
API_BASE      = "https://api.mercadolibre.com"
DEFAULT_IMG   = "https://via.placeholder.com/150"

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


def parse_order_data(order_data: dict) -> dict:
    """
    De un JSON /orders/{order_id}, extraer:
      - titulo
      - sku
      - variante
      - cantidad
      - imágenes
    y devolver un diccionario con la forma:
      {
        "cliente": <nick del buyer>,
        "items": [
          { "titulo": ..., "sku": ..., "variante": ..., "cantidad": ..., "imagenes": [ {url, thumbnail}, ... ] },
          ...
        ]
      }
    """
    DEFAULT_IMG_LOCAL = DEFAULT_IMG
    cliente = order_data.get("buyer", {}).get("nickname", "Cliente desconocido")

    raw_items = order_data.get("order_items", [])
    # En algunos casos vienen en "items" en lugar de "order_items"
    if not raw_items:
        raw_items = order_data.get("items", [])

    items = []
    for oi in raw_items:
        # Si viene la forma order_items, el item real está en oi["item"]
        prod = oi.get("item", oi)

        titulo   = prod.get("title", "Sin título")
        cantidad = oi.get("quantity", 0)

        # Variante: revisamos variation_attributes, si existe
        attrs = prod.get("variation_attributes", [])
        if attrs:
            variante = " | ".join(f"{a['name']}: {a['value_name']}" for a in attrs if a.get("value_name"))
        else:
            variante = "—"

        # SKU: siguiendo la doc de ML, primero seller_sku de variación, sino seller_custom_field de variación,
        # luego seller_sku de item, luego seller_custom_field de item.
        sku = (
            prod.get("seller_sku")
            or prod.get("seller_custom_field")
            or oi.get("seller_custom_field")
            or oi.get("seller_sku")
            or "Sin SKU"
        )

        # Construir lista de imágenes:
        imgs = []
        variation_id = prod.get("variation_id")
        if variation_id:
            # Si existe variation_id, pedimos /items/{item_id}/variations/{variation_id}
            v = fetch_api(f"/items/{prod['id']}/variations/{variation_id}")
            for pid in v.get("picture_ids", []):
                #  ML convention: D_{picture_id}-O.jpg → imagen full, D_{picture_id}-I.jpg → thumbnail
                imgs.append({
                    "url":       f"https://http2.mlstatic.com/D_{pid}-O.jpg",
                    "thumbnail": f"https://http2.mlstatic.com/D_{pid}-I.jpg"
                })
        else:
            # Si no hay variation_id, pedimos /items/{item_id}
            p = fetch_api(f"/items/{prod['id']}")
            for pic in p.get("pictures", []):
                imgs.append({
                    "url":       pic.get("url", DEFAULT_IMG_LOCAL),
                    "thumbnail": pic.get("secure_url", DEFAULT_IMG_LOCAL)
                })

        if not imgs:
            imgs = [{"url": DEFAULT_IMG_LOCAL, "thumbnail": DEFAULT_IMG_LOCAL}]

        items.append({
            "titulo":   titulo,
            "sku":      sku,
            "variante": variante,
            "cantidad": cantidad,
            "imagenes": imgs,
            "item_id": prod.get("id"),
            "variation_id": prod.get("variation_id")
        })

    return {"cliente": cliente, "items": items}

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
            if cache.fecha_consulta and datetime.utcnow() - cache.fecha_consulta < timedelta(minutes=TTL_MINUTOS):
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

async def fetch_item_permalink(session, item_id, token, db):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                permalink = data.get("permalink")

                # Guardar en cache si existe el item
                item_db = db.query(WsItem).filter_by(item_id=item_id).first()
                if item_db:
                    item_db.permalink = permalink
                    item_db.actualizado = datetime.utcnow()
                else:
                    item_db = WsItem(
                        item_id=item_id,
                        permalink=permalink,
                        actualizado=datetime.utcnow()
                    )
                    db.add(item_db)
                db.commit()

                return item_id, permalink
    except Exception as e:
        logger.warning("Error al consultar item_id=%s: %s", item_id, e)
    return item_id, None
    
async def enriquecer_permalinks(items: list, token: str, db: Session):
    async with aiohttp.ClientSession() as session:
        tareas = []
        for item in items:
            item_id = item.get("item_id")
            if item_id:
                tareas.append(fetch_item_permalink(session, item_id, token, db))

        resultados = await asyncio.gather(*tareas)

        # Asignar resultados a los items originales
        permalink_map = {item_id: permalink for item_id, permalink in resultados}
        for item in items:
            item_id = item.get("item_id")
            item["permalink"] = permalink_map.get(item_id)


async def enriquecer_items_ws(items: list, db: Session):
    sku_cache = {}

    async def enriquecer(item):
        sku = item.get("sku")
        if not sku:
            return
        if sku in sku_cache:
            info = sku_cache[sku]
        else:
            info = await asyncio.to_thread(buscar_item_cache_por_sku, db, sku)
            sku_cache[sku] = info
        if info:
            item["codigo_proveedor"] = info.item_vendorcode
            item["item_vendorcode"] = info.item_vendorcode  # ✅ opcional si querés mostrar en columna tabla
            item["codigo_alfa"] = info.item_vendorcode      # ✅ esto evita el error y mantiene compatibilidad visual

    await asyncio.gather(*(enriquecer(item) for item in items))
