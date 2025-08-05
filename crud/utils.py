import asyncio
import aiohttp
from ws.auth import autenticar_desde_json
from ws.items import obtener_todos_los_items, parsear_items
from sqlalchemy.orm import Session
from database.models import WsItem
from api_ml import fetch_api, fetch_item_permalink

DEFAULT_IMG   = "https://via.placeholder.com/150"


def buscar_item_cache_por_sku(db: Session, sku: str):
    return db.query(WsItem).filter(WsItem.item_code == sku).first()

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
    skus_faltantes = set()

    # 1. Buscar en caché local
    for item in items:
        sku = item.get("sku")
        if not sku:
            continue
        info = buscar_item_cache_por_sku(db, sku)
        if info:
            sku_cache[sku] = {
                 "item_vendorCode": info.item_vendorCode
            }
        else:
            skus_faltantes.add(sku)

    # 2. Si hay faltantes, consultar el WS UNA vez
    if skus_faltantes:
        print(f"🔍 Buscando {len(skus_faltantes)} SKUs faltantes desde Web Service...")
        token = await asyncio.to_thread(autenticar_desde_json)
        xml = await asyncio.to_thread(obtener_todos_los_items, token)
        ws_items = await asyncio.to_thread(parsear_items, xml)

        nuevos_ws_items = []

        for ws_data in ws_items:
            item_code = ws_data["item_code"]
            if item_code in skus_faltantes:
                sku_cache[item_code] = {
                    "item_vendorCode": ws_data["item_vendorCode"]
                }

                # Crear objeto para guardar en DB
                # ✅ CORRECTO
            nuevos_ws_items.append(WsItem(
            item_id=ws_data["item_id"],
            item_code=ws_data["item_code"],
            item_vendorCode=ws_data["item_vendorCode"]  # ✅ corregido
            ))


        # Guardar nuevos ítems en la base de datos
        if nuevos_ws_items:
            db.bulk_save_objects(nuevos_ws_items)
            db.commit()
            print(f"✅ {len(nuevos_ws_items)} ítems nuevos agregados al cache.")

    # 3. Enriquecer los ítems con los datos ya en memoria
    for item in items:
        sku = item.get("sku")
        if not sku:
            continue
        info = sku_cache.get(sku)
        if info:
            item["codigo_proveedor"] = info["item_vendorCode"]
            item["item_vendorCode"] = info["item_vendorCode"]
            item["codigo_alfa"] = info["item_vendorCode"]