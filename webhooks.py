# webhooks.py
import asyncio
from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal
from database.models import MLPedidoCache
from datetime import datetime, timezone
from api_ml import fetch_order_basic, parse_order_data_light, get_valid_token
from api_ml import get_order_details, upsert_cache_basic  # reutilizamos el pesado para el BG

webhooks = APIRouter()

def enrich_bg(shipment_id: str):
    db = SessionLocal()
    try:
        import asyncio
        asyncio.run(get_order_details(shipment_id=shipment_id, db=db))  # esto ya escribe todo con imágenes
        rec = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).one_or_none()
        if rec and hasattr(rec, "is_enriched"):
            rec.is_enriched = True
            rec.last_enriched_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

@webhooks.post("/ml")
async def recibir_webhook_ml(request: Request, background: BackgroundTasks):
    data = await request.json()
    topic = data.get("topic") or ""
    resource = data.get("resource") or ""

    order_id = shipment_id = None
    if resource.startswith("/orders/"):
        order_id = resource.rsplit("/", 1)[-1]
    elif resource.startswith("/shipments/"):
        shipment_id = resource.rsplit("/", 1)[-1]

    db = SessionLocal()
    try:
        # Si llegó order_id, con UNA llamada resuelvo todo lo básico
        if order_id and not shipment_id:
            od = fetch_order_basic(order_id)
            shipment_id = str(od.get("shipping", {}).get("id") or "")
            parsed_light = parse_order_data_light(od, shipment_id=shipment_id)
            if shipment_id:
                upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id, parsed_light=parsed_light)
                background.add_task(enrich_bg, shipment_id)  # pesado en BG
                return {"ok": True, "mode": "order_light", "shipment_id": shipment_id}

        # Si llegó shipment directamente, podés (opcional) traer order básico:
        if shipment_id and not order_id:
            try:
                # 1 sola llamada para order_id + buyer/estado desde /orders/{id}
                # (algunas cuentas requieren /shipments/{id} primero para sacar order_id)
                from api_ml import fetch_api
                ship = fetch_api(f"/shipments/{shipment_id}")
                order_id = str(ship.get("order_id") or (ship.get("order") or {}).get("id") or "")
                od = fetch_order_basic(order_id) if order_id else None
                parsed_light = parse_order_data_light(od, shipment_id=shipment_id) if od else {
                    "cliente": None, "estado_envio": ship.get("status"), "estado_ml": None, "items": []
                }
                upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id, parsed_light=parsed_light)
            except Exception:
                # si falla, al menos registrá el shipment para que el dashboard cuente
                upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id or "", parsed_light={
                    "cliente": None, "estado_envio": None, "estado_ml": None, "items": []
                })

            background.add_task(enrich_bg, shipment_id)
            return {"ok": True, "mode": "shipment_light", "shipment_id": shipment_id}

    finally:
        db.close()

    return {"ok": True, "skipped": True}
