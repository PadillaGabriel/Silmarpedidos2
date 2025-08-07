# webhooks.py
import asyncio
from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal
from database.models import MLPedidoCache
from datetime import datetime, timezone

webhooks = APIRouter()

def upsert_minimo(db: Session, *, shipment_id: str|None, order_id: str|None, estado_ml: str|None, logistic_type: str|None, detalle_raw: dict):
    obj = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).one_or_none() if shipment_id else None
    if not obj:
        obj = MLPedidoCache(shipment_id=shipment_id, order_id=order_id)
        db.add(obj)
    # no pisamos con None
    if order_id: obj.order_id = order_id
    if estado_ml: obj.estado_ml = estado_ml
    if logistic_type: obj.logistic_type = logistic_type
    obj.fecha_consulta = datetime.now(timezone.utc)
    obj.detalle_raw = detalle_raw  # opcional
    db.commit()

def enriquecer_por_shipment(shipment_id: str):
    db = SessionLocal()
    try:
        # usa TU flujo "bueno" por shipment_id
        # importante: no bloquear el request del webhook
        import api_ml
        detalle = asyncio.run(api_ml.get_order_details(shipment_id=shipment_id, db=db))
        # marcar enriquecido
        rec = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).one_or_none()
        if rec:
            rec.is_enriched = True
            rec.last_enriched_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as e:
        print(f"⚠️ enrich {shipment_id} fallo: {e}")
        db.rollback()
    finally:
        db.close()

@webhooks.post("/ml")
async def recibir_webhook_ml(request: Request, background: BackgroundTasks):
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "detail": "Invalid JSON"}

    topic = data.get("topic")
    resource = data.get("resource") or ""
    order_id = shipment_id = None

    if resource.startswith("/orders/"):
        order_id = resource.split("/")[-1]
    if resource.startswith("/shipments/"):
        shipment_id = resource.split("/")[-1]

    # Si vino order y no shipment, resolvelo rápido con 1 llamada (o dejalo para el enrich)
    if not shipment_id and order_id:
        try:
            from api_ml import fetch_api
            od = fetch_api(f"/orders/{order_id}")
            shipment_id = str(od.get("shipping", {}).get("id") or "")
        except Exception:
            pass

    db = SessionLocal()
    try:
        # Guardado mínimo
        upsert_minimo(
            db,
            shipment_id=shipment_id,
            order_id=order_id,
            estado_ml=None,           # si lo tenés del payload, pasalo
            logistic_type=None,       # idem
            detalle_raw=data
        )
        # Enriquecer en background (no bloquear)
        if shipment_id:
            background.add_task(enriquecer_por_shipment, shipment_id)
    finally:
        db.close()

    return {"status": "ok"}
