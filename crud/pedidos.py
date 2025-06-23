from datetime import datetime
from database.connection import Session
from database.models import Pedido

def add_order_if_not_exists(detalle):
    session = Session()
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
    session = Session()
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
    session = Session()
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
    session = Session()
    pedido = session.query(Pedido.estado).filter_by(shipment_id=shipment_id).first()
    session.close()
    return pedido[0] if pedido else None

def get_all_pedidos(order_id=None, shipment_id=None, date_from=None, date_to=None, logistica=None):
    session = Session()
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

