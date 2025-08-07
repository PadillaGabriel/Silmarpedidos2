from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from api_ml import get_order_details, guardar_pedido_en_cache, fetch_api
from database.connection import SessionLocal

webhooks = APIRouter()


@webhooks.post("/ml")
async def recibir_webhook_ml(request: Request):
    try:
        data = await request.json()
        print("📦 Webhook recibido (raw JSON):", data)
    except Exception as e:
        print("❌ Error al leer el cuerpo del webhook:", e)
        return {"status": "error", "detail": "Invalid JSON"}

    topic = data.get("topic")
    resource = data.get("resource")
    print(f"🔔 Notificación recibida: {topic} → {resource}")


    if topic in ["orders", "orders_v2"] and resource and resource.startswith("/orders/"):
        order_id = resource.split("/")[-1]
        db = SessionLocal()
        try:
            # 🔧 Traer JSON crudo de la orden
            order_raw = fetch_api(f"/orders/{order_id}")
            # 💾 Guardar directo en cache con datos reales
            await guardar_pedido_en_cache(order_raw, db, order_id)
            print(f"✅ Pedido {order_id} guardado en caché")
        except Exception as e:
            print(f"❌ Error procesando pedido {order_id}: {e}")
        finally:
            db.close()
    return {"status": "ok"}