# crud/utils_ml.py
import asyncio
from datetime import datetime, timezone
import aiohttp
import logging
from ws.items import obtener_todos_los_items, parsear_items
from crud.pedidos import buscar_item_cache_por_sku
from auth_ml import  autenticar_desde_json
from database.models import MLItem, WsItem
from sqlalchemy.orm import Session

# Logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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

async def fetch_item_permalink(session, item_id, token, db):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                permalink = data.get("permalink")

                # Guardar en cache si existe el item
                item_db = db.query(MLItem).filter_by(item_id=item_id).first()
                if item_db:
                    item_db.permalink = permalink
                    item_db.actualizado = datetime.now(timezone.utc)
                else:
                    item_db = MLItem(
                        item_id=item_id,
                        permalink=permalink,
                        actualizado=datetime.now(timezone.utc)
                    )
                    db.add(item_db)
                db.commit()


                return item_id, permalink
    except Exception as e:
        logger.warning("Error al consultar item_id=%s: %s", item_id, e)
    return item_id, None
    
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








