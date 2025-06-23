# api_ml.py

import json
import logging
import requests
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

def get_order_details(order_id: str = None, shipment_id: str = None) -> dict:
    """
    Flujo completo:
      1) Si me mandan order_id: hago GET /orders/{order_id} y devuelvo parse_order_data + primer_order_id=order_id.
      2) Si me mandan shipment_id: hago GET /shipments/{shipment_id}/items (with x-format-new: true)
         -> eso me devuelve un array de entradas, cada una con item_id, variation_id, quantity, order_id, ...
         Luego, para cada entry hago GET /orders/{order_id} y filtro únicamente el ítem que coincida
         con item_id+variation_id, acumulándolo en all_items. El primer order_id que encuentre lo guardo en primer_oid.
    """
    token = get_valid_token()
    if not token:
        logger.error("No se obtuvo token válido")
        return {"cliente": "Error", "items": [], "primer_order_id": None}

    common_headers = {"Authorization": f"Bearer {token}"}

    # ------------------------------ 1) Búsqueda directa por order_id ------------------------------
    if order_id:
        try:
            od = fetch_api(f"/orders/{order_id}", extra_headers=common_headers)
            parsed = parse_order_data(od)
            # Como vinimos con order_id directo, devolvemos ese mismo como primer_order_id:
            parsed["primer_order_id"] = order_id
            return parsed
        except Exception as e:
            logger.warning("/orders/%s devolvió error: %s", order_id, e)

    # ------------------------------ 2) Si vino shipment_id → /shipments/{shipment_id}/items ------------------------------
    if shipment_id:
        try:
            shipment_items = fetch_api(
                f"/shipments/{shipment_id}/items",
                extra_headers={**common_headers, "x-format-new": "true"}
            )
            # Ahora shipment_items debería ser una lista de objetos:
            # [
            #   {
            #     "item_id": "MLA1703763596",
            #     "variation_id": 186044755919,
            #     "quantity": 1,
            #     "order_id": "2000011777021922",
            #     "user_product_id": "MLAU2759307141",
            #     "description": "Mesa Bandeja ...",
            #     ...
            #   },
            #   { ... segunda entrada ... }
            # ]
            try:
                shipment_data = fetch_api(f"/shipments/{shipment_id}", extra_headers=common_headers)
                shipment_status = shipment_data.get("status", "desconocido")
            except Exception as e:
                logger.warning("No se pudo obtener el estado del envío: %s", e)
                shipment_status = "desconocido"

                #  Traducción a español
            estado_traducido = {
                "pending": "Pendiente",
                "ready_to_ship": "Listo para enviar",
                "shipped": "Enviado",
                "delivered": "Entregado",
                "not_delivered": "No entregado",
                "cancelled": "Cancelado",
                "returned": "Devuelto"
            }
            estado_envio = estado_traducido.get(shipment_status, shipment_status.capitalize())

            if not isinstance(shipment_items, list) or len(shipment_items) == 0:
                logger.error("No hay shipping_items para shipment_id=%s", shipment_id)
                return {"cliente": "Error", "items": [], "primer_order_id": None, "shipment_status": shipment_status}


            all_items  = []
            cliente    = None
            primer_oid = None

            # Para cada entry en shipment_items pedimos la orden y filtramos el item correspondiente
            for idx, entry in enumerate(shipment_items):
                oid = entry.get("order_id")
                if not oid:
                    continue

                # Guardamos el primer order_id que aparezca en el array
                if primer_oid is None:
                    primer_oid = oid

                # Pedimos el JSON completo de la order
                try:
                    od = fetch_api(f"/orders/{oid}", extra_headers=common_headers)
                except Exception as e:
                    logger.warning("/orders/%s devolvió error: %s", oid, e)
                    continue

                # Cliente: solo lo asignamos la primera vez
                if cliente is None:
                    cliente = od.get("buyer", {}).get("nickname", "Cliente desconocido")

                # Buscamos en od["order_items"] el item cuyo id y variation_id coincidan con la entry
                for oi in od.get("order_items", []):
                    prod = oi.get("item", oi)
                    if (
                        prod.get("id") == entry.get("item_id")
                        and prod.get("variation_id") == entry.get("variation_id")
                    ):
                        # Reconstruimos un mini-JSON con esa sola línea
                        temp_order = {
                            "buyer":      od.get("buyer", {}),
                            "order_items": [oi]
                        }
                        detalle_unico = parse_order_data(temp_order)
                        # Enriquecer cada ítem con permalink
                    for item in detalle_unico.get("items", []):
                        item_id = entry.get("item_id")
                        try:
                            item_data = fetch_api(f"/items/{item_id}", extra_headers=common_headers)
                            item["permalink"] = item_data.get("permalink")
                        except Exception as e:
                            logger.warning("No se pudo obtener permalink de item_id=%s: %s", item_id, e)

                        # parse_order_data(…) nos devuelve:
                        # { "cliente": "...", "items": [ {titulo, sku, variante, cantidad, imagenes}, … ] }
                        if detalle_unico.get("items"):
                            all_items.extend(detalle_unico["items"])
                        break

            if all_items:
                 return {
                "cliente": cliente or "Cliente desconocido",
                "items": all_items,
                "primer_order_id": primer_oid,
                "shipment_status": shipment_status,  # ← este es el que te falta
                "estado_envio": estado_envio
            }


            logger.error("No se obtuvieron ítems tras procesar shipment_id=%s", shipment_id)
        except Exception as e:
            logger.warning("Error procesando /shipments/%s/items: %s", shipment_id, e)

    # ------------------------------ 3) Fallback: no se encontró order ni shipment válido ------------------------------
    logger.error(
        "No se encontró order ni shipment válido (order_id=%s, shipment_id=%s)",
        order_id, shipment_id
    )
    return {"cliente": "Error", "items": [], "primer_order_id": None}