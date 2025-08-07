# webhooks.py
import asyncio
import logging
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
logger = logging.getLogger("uvicorn.error")
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
    logger.info("📬 ML webhook: topic=%s resource=%s", topic, resource)

    # ... (tu parseo de order_id/shipment_id) ...
    logger.info("🆔 IDs parseados -> order_id=%s shipment_id=%s", order_id, shipment_id)

    db = SessionLocal()
    try:
        # --- ORDER ---
        if order_id and not shipment_id:
            od = fetch_order_basic(order_id)
            if od is None:
                logger.warning("⚠️ /orders/%s no accesible, usando fallback /orders/search", order_id)
                token = get_valid_token()
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                od = buscar_order_completo(order_id, headers)

            if od:
                shipment_id = str(od.get("shipping", {}).get("id") or "")
                if not shipment_id:
                    logger.warning("⚠️ order_id=%s sin shipment_id; se omite upsert", order_id)
                    return {"ok": True, "mode": "order_no_shipment"}

                parsed_light = parse_order_data_light(od, shipment_id=shipment_id)
                logger.info(
                    "📝 Upsert light (ORDER) sid=%s oid=%s cliente=%s estado_envio=%s estado_ml=%s items=%d",
                    shipment_id, order_id,
                    parsed_light.get("cliente"),
                    parsed_light.get("estado_envio"),
                    parsed_light.get("estado_ml"),
                    len(parsed_light.get("items") or []),
                )
                upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id, parsed_light=parsed_light)

                # verificación inmediata post-commit
                rec = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).one_or_none()
                if rec:
                    logger.info(
                        "✅ Cache guardada sid=%s oid=%s cliente=%s estado_envio=%s items=%d",
                        rec.shipment_id, rec.order_id, rec.cliente, rec.estado_envio, len(rec.detalle or [])
                    )
                else:
                    logger.error("❌ No se encontró el registro recién guardado (sid=%s)", shipment_id)

                background.add_task(enrich_bg, shipment_id)
                return {"ok": True, "mode": "order_light", "shipment_id": shipment_id}

        # --- SHIPMENT ---
        if shipment_id and not order_id:
            try:
                from api_ml import fetch_api
                ship = fetch_api(f"/shipments/{shipment_id}")
                order_id = str(ship.get("order_id") or (ship.get("order") or {}).get("id") or "")
            except Exception as e:
                logger.warning("⚠️ /shipments/%s fallo: %s", shipment_id, e)
                order_id = ""

            od = fetch_order_basic(order_id) if order_id else None
            parsed_light = (
                parse_order_data_light(od, shipment_id=shipment_id)
                if od else {"cliente": None, "estado_envio": ship.get("status") if 'ship' in locals() else None, "estado_ml": None, "items": []}
            )
            logger.info(
                "📝 Upsert light (SHIPMENT) sid=%s oid=%s cliente=%s estado_envio=%s estado_ml=%s items=%d",
                shipment_id, order_id or "",
                parsed_light.get("cliente"),
                parsed_light.get("estado_envio"),
                parsed_light.get("estado_ml"),
                len(parsed_light.get("items") or []),
            )
            upsert_cache_basic(db, shipment_id=shipment_id, order_id=order_id or "", parsed_light=parsed_light)

            rec = db.query(MLPedidoCache).filter_by(shipment_id=shipment_id).one_or_none()
            if rec:
                logger.info(
                    "✅ Cache guardada sid=%s oid=%s cliente=%s estado_envio=%s items=%d",
                    rec.shipment_id, rec.order_id, rec.cliente, rec.estado_envio, len(rec.detalle or [])
                )
            else:
                logger.error("❌ No se encontró el registro recién guardado (sid=%s)", shipment_id)

            background.add_task(enrich_bg, shipment_id)
            return {"ok": True, "mode": "shipment_light", "shipment_id": shipment_id}

        logger.info("↪️ Notificación omitida (resource=%s)", resource)
        return {"ok": True, "skipped": True}

    finally:
        db.close()
