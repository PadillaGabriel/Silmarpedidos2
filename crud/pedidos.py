from datetime import datetime
from database.models import MLPedidoCache
from sqlalchemy.dialects.postgresql import JSONB
from database.connection import SessionLocal  # ✅ correcto
from database.models import Pedido, WsItem
from sqlalchemy.orm import Session        # ✅ Correcto
from api_ml import enriquecer_permalinks, enriquecer_items_ws, parse_order_data
from auth_ml import obtener_token

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
    cache = MLPedidoCache(
        shipment_id=shipment_id,
        order_id=order_id,
        cliente=cliente,
        estado_envio=estado_envio,
        estado_ml=estado_ml,
        detalle=detalle
    )
    db.merge(cache)  # actualiza si existe
    print("💾 Commit a la base de datos")

    db.commit()
    verificado = db.query(MLPedidoCache).filter_by(order_id=order_id).first()
    if not verificado:
        print("❌ Commit realizado pero no se encuentra el pedido guardado.")



async def guardar_pedido_en_cache(pedido: dict, db: Session):
    print(f"🧩 Ejecutando guardar_pedido_en_cache con order_id={order_id}")

    try:
        order_id = pedido["id"]
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



