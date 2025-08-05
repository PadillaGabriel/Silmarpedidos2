import asyncio
from datetime import datetime, timedelta, timezone
import logging

import aiohttp  # Usado para enriquecer permalinks
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Pedido, WsItem, MLPedidoCache, MLItem  # ✅ agregué MLItem si usás fetch_item_permalink
from auth_ml import obtener_token
from api_ml import fetch_api  # solo este si el resto ya quedó dentro de api_ml
from ws.items import buscar_item_por_sku,parsear_items,obtener_todos_los_items
from ws.auth import autenticar_desde_json
from sqlalchemy.orm import Session
from database.models import WsItem

DEFAULT_IMG   = "https://via.placeholder.com/150"


def add_order_if_not_exists(detalle):
    session = SessionLocal()
    for item in detalle["items"]:
        exists = session.query(Pedido).filter_by(
            shipment_id=item["shipment_id"],
            order_id=item["order_id"]
        ).first()
        if not exists:
            session.add(Pedido(
                order_id=item["order_id"],
                cliente=detalle["cliente"],
                titulo=item["titulo"],
                cantidad=item["cantidad"],
                estado="pendiente",
                shipment_id=item["shipment_id"]
            ))
    session.commit()
    session.close()

def marcar_envio_armado(shipment_id, usuario):
    session = SessionLocal()
    ahora = datetime.now()
    filas = session.query(Pedido).filter_by(shipment_id=shipment_id, estado="pendiente").update({
        Pedido.estado: "armado",
        Pedido.fecha_armado: ahora,
        Pedido.usuario_armado: usuario
    })
    session.commit()
    session.close()
    return filas > 0

def marcar_pedido_despachado(shipment_id, logistica, tipo_envio, usuario):
    session = SessionLocal()
    ahora = datetime.now()
    filas = session.query(Pedido).filter_by(shipment_id=shipment_id, estado="armado").update({
        Pedido.estado: "despachado",
        Pedido.fecha_despacho: ahora,
        Pedido.logistica: logistica,
        Pedido.tipo_envio: tipo_envio,
        Pedido.usuario_despacho: usuario
    })
    session.commit()
    session.close()
    return filas > 0

def get_estado_envio(shipment_id):
    session = SessionLocal()
    pedido = session.query(Pedido.estado).filter_by(shipment_id=shipment_id).first()
    session.close()
    return pedido[0] if pedido else None

def get_all_pedidos(order_id=None, shipment_id=None, date_from=None, date_to=None, logistica=None):
    session = SessionLocal()
    query = session.query(Pedido)

    if order_id:
        query = query.filter(Pedido.order_id.ilike(f"%{order_id}%"))
    if shipment_id:
        query = query.filter(Pedido.shipment_id.ilike(f"%{shipment_id}%"))
    if date_from:
        query = query.filter((Pedido.fecha_armado >= date_from) | (Pedido.fecha_despacho >= date_from))
    if date_to:
        query = query.filter((Pedido.fecha_armado <= date_to) | (Pedido.fecha_despacho <= date_to))
    if logistica:
        query = query.filter(Pedido.logistica == logistica)

    rows = query.all()
    session.close()

    return [{
        "order_id": r.order_id,
        "cliente": r.cliente,
        "titulo": r.titulo,
        "cantidad": r.cantidad,
        "estado": r.estado,
        "fecha_armado": r.fecha_armado.strftime("%Y-%m-%d %H:%M:%S") if r.fecha_armado else None,
        "fecha_despacho": r.fecha_despacho.strftime("%Y-%m-%d %H:%M:%S") if r.fecha_despacho else None,
        "logistica": r.logistica,
        "shipment_id": r.shipment_id,
        "tipo_envio": r.tipo_envio,
        "usuario_armado": r.usuario_armado,
        "usuario_despacho": r.usuario_despacho
    } for r in rows]


def limpiar_cache_antiguo(db: Session, dias: int = 30):
    from datetime import datetime, timedelta
    limite = datetime.now() - timedelta(days=dias)
    db.query(MLPedidoCache).filter(MLPedidoCache.fecha_consulta < limite).delete()
    db.commit()

def guardar_pedido_cache(db: Session, shipment_id: str, order_id: str, cliente: str, estado_envio: str, estado_ml: str, detalle: dict):
    try:
        cache = MLPedidoCache(
            shipment_id=shipment_id,
            order_id=order_id,
            cliente=cliente,
            estado_envio=estado_envio,
            estado_ml=estado_ml,
            detalle=detalle
        )

        db.merge(cache)  # actualiza si ya existe
        db.commit()
        print(f"💾 Pedido {order_id} commit a la base de datos")

        # Validación extra
        verificado = db.query(MLPedidoCache).filter_by(order_id=order_id).first()
        if verificado:
            print(f"🟢 Pedido verificado en base: {verificado.order_id}")
        else:
            print(f"❌ Commit realizado pero no se encuentra el pedido guardado con order_id={order_id}")

    except Exception as e:
        print(f"💥 Error al guardar pedido {order_id}: {e}")


async def guardar_pedido_en_cache(pedido: dict, db: Session):
    try:
        order_id = pedido["id"]
        print(f"🧩 Ejecutando guardar_pedido_en_cache con order_id={order_id}")

        shipment_id = pedido.get("shipping", {}).get("id")
        cliente = pedido.get("buyer", {}).get("nickname", "")
        estado_ml = pedido.get("status", "unknown")
        estado_envio = pedido.get("shipping", {}).get("status", "sin_envio")

        parsed = parse_order_data(pedido)
        items = parsed.get("items", [])

        # Enriquecer datos como imagen, SKU y Alfa
        token = obtener_token()
        await enriquecer_permalinks(items, token, db)
        await enriquecer_items_ws(items, db)

        guardar_pedido_cache(
            db=db,
            shipment_id=shipment_id,
            order_id=order_id,
            cliente=cliente,
            estado_envio=estado_envio,
            estado_ml=estado_ml,
            detalle=items  # ¡ya enriquecidos!
        )
        print(f"✅ Pedido {order_id} enriquecido y guardado en caché.")
    except Exception as e:
        print(f"❌ Error al guardar pedido {pedido.get('id')}: {e}")

def marcar_pedido_con_feedback(order_id: int, db: Session):
    pedido = db.query(MLPedidoCache).filter_by(order_id=order_id).first()
    if pedido:
        pedido.con_feedback = True
        db.commit()
        print(f"✅ Pedido {order_id} marcado con feedback.")
    else:
        print(f"⚠️ Pedido {order_id} no encontrado para marcar feedback.")


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

def buscar_item_cache_por_sku(db: Session, sku: str):
    return db.query(WsItem).filter(WsItem.item_code == sku).first()
