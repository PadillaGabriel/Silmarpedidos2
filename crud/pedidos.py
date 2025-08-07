import asyncio
from datetime import datetime, timedelta, timezone
import logging

import aiohttp  # Usado para enriquecer permalinks
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Pedido, WsItem, MLPedidoCache, MLItem  # ✅ agregué MLItem si usás fetch_item_permalink
from ws.items import buscar_item_por_sku, parsear_items,obtener_todos_los_items
from ws.auth import autenticar_desde_json
from sqlalchemy.orm import Session
from database.models import WsItem



def add_order_if_not_exists(detalle):
    session = SessionLocal()
    for item in detalle["items"]:
        exists = session.query(Pedido).filter_by(
            shipment_id=item["shipment_id"],
            order_id=item["order_id"],
            titulo=item["titulo"],  # Podés usar item_id o variation_id si querés más precisión
        ).first()

        if not exists:
            session.add(Pedido(
                order_id=item["order_id"],
                shipment_id=item["shipment_id"],
                cliente=detalle["cliente"],
                titulo=item["titulo"],
                cantidad=item["cantidad"],
                estado="pendiente"
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

def marcar_pedido_despachado(db: Session, shipment_id, logistica, tipo_envio, usuario):
    ahora = datetime.now()

    pedidos = db.query(Pedido).filter(Pedido.shipment_id == shipment_id).all()

    if not pedidos:
        print(f"❌ No se encontró ningún pedido con shipment_id={shipment_id}")
        return False

    if any(p.estado != "armado" for p in pedidos):
        print(f"⚠️ Hay ítems que aún no están armados para shipment_id={shipment_id}")
        return False

    # Validar cancelación usando el primer pedido (todos comparten order_id y shipment_id)
    pedido_cache = db.query(MLPedidoCache).filter_by(order_id=pedidos[0].order_id).first()
    if pedido_cache and pedido_cache.estado_ml == "cancelled":
        raise Exception("🚫 El pedido está cancelado y no se puede despachar.")

    for pedido in pedidos:
        pedido.estado = "despachado"
        pedido.fecha_despacho = ahora
        pedido.logistica = logistica
        pedido.tipo_envio = tipo_envio
        pedido.usuario_despacho = usuario

    db.commit()
    print(f"✅ Shipment {shipment_id} marcado como despachado por {usuario}")
    return True

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


def marcar_pedido_con_feedback(order_id: int, db: Session):
    pedido = db.query(MLPedidoCache).filter_by(order_id=order_id).first()
    if pedido:
        pedido.con_feedback = True
        db.commit()
        print(f"✅ Pedido {order_id} marcado con feedback.")
    else:
        print(f"⚠️ Pedido {order_id} no encontrado para marcar feedback.")


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








