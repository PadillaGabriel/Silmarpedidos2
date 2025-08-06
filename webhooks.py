from fastapi import APIRouter, Request
from api_ml import get_order_details
from api_ml import guardar_pedido_en_cache
from database.connection import SessionLocal

webhooks = APIRouter()

@webhooks.post("/ml")
async def recibir_webhook_ml(request: Request):
    try:
        data = await request.json()
        print("📦 Webhook recibido (raw JSON):", data)  # 👈👈 MOSTRAR EL JSON RECIBIDO
    except Exception as e:
        print("❌ Error al leer el cuerpo del webhook:", e)
        return {"status": "error", "detail": "Invalid JSON"}

    topic = data.get("topic")
    resource = data.get("resource")
    print(f"🔔 Notificación recibida: {topic} → {resource}")

    if topic in ["orders", "orders_v2"] and resource.startswith("/orders/"):
        order_id = resource.split("/")[-1]
        try:
            parsed = await get_order_details(order_id)
            if parsed:
                db = SessionLocal()
                try:
                    await guardar_pedido_en_cache(parsed, db, order_id)
                    print(f"✅ Pedido {order_id} guardado en caché")
                finally:
                    db.close()
            else:
                print(f"⚠️ Pedido {order_id} vacío o inválido")
        except Exception as e:
            print(f"❌ Error procesando pedido {order_id}: {e}")

    return {"status": "ok"}