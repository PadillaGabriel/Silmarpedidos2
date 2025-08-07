# webhooks.py
import asyncio
import re
from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal
from database.models import MLPedidoCache
from datetime import datetime, timezone
# webhooks.py
from api_ml import (
    fetch_order_basic,
    parse_order_data_light,
    get_valid_token,
    get_order_details,
    upsert_cache_basic,
    buscar_order_completo,          # 👈 importar esto para el fallback
)

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
    resource = data.get("resource") or ""

    # Extraer SOLO IDs numéricos (evita /orders/feedback, etc.)
    order_id = None
    shipment_id = None

    m = re.match(r"^/orders/(\d+)(?:/.*)?$", resource)
    if m:
        order_id = m.group(1)

    m = re.match(r"^/shipments/(\d+)", resource)
    if m:
        shipment_id = m.group(1)

    db = SessionLocal()
    try:
        # --- Notificación por ORDER ---
        if order_id and not shipment_id:
            od = fetch_order_basic(order_id)

            # Fallback si /orders/{id} devuelve 401/403/404
            if od is None:
                token = get_valid_token()
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                od = buscar_order_completo(order_id, headers)  # usa /orders/search internamente

            if not od:
                # No hay acceso a la orden: no crashea, solo registra "skipped"
                return {"ok": True, "skipped": True, "reason": "order_not_accessible"}

            shipment_id = str(od.get("shipping", {}).get("id") or "")
            if not shipment_id:
                return {"ok": True, "mode": "order_no_shipment"}

            parsed_light = parse_order_data_light(od, shipment_id=shipment_id)
            upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id, parsed_light=parsed_light)
            background.add_task(enrich_bg, shipment_id)
            return {"ok": True, "mode": "order_light", "shipment_id": shipment_id}

        # --- Notificación por SHIPMENT ---
        if shipment_id and not order_id:
            ship_status = None
            try:
                from api_ml import fetch_api
                ship = fetch_api(f"/shipments/{shipment_id}")
                ship_status = ship.get("status")
                order_id = str(ship.get("order_id") or (ship.get("order") or {}).get("id") or "")
            except Exception:
                ship = {}
                order_id = ""

            od = fetch_order_basic(order_id) if order_id else None
            parsed_light = (
                parse_order_data_light(od, shipment_id=shipment_id)
                if od else {"cliente": None, "estado_envio": ship_status, "estado_ml": None, "items": []}
            )

            upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id, parsed_light=parsed_light)
            background.add_task(enrich_bg, shipment_id)
            return {"ok": True, "mode": "shipment_light", "shipment_id": shipment_id}

        # Si no es un recurso que nos interese (p.ej. /orders/feedback)
        return {"ok": True, "skipped": True}

    finally:
        db.close()