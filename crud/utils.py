import asyncio
import aiohttp
from ws.auth import autenticar_desde_json
from ws.items import obtener_todos_los_items, parsear_items
from sqlalchemy.orm import Session
from database.models import WsItem



def buscar_item_cache_por_sku(db: Session, sku: str):
    return db.query(WsItem).filter(WsItem.item_code == sku).first()



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