from fastapi import APIRouter, Request
import httpx
from auth_ml import get_ml_token
from crud.pedidos import guardar_pedido_en_cache

webhooks = APIRouter()

@webhooks.post("/ml")
async def recibir_webhook_ml(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        print("❌ Error al leer el cuerpo del webhook:", e)
        return {"status": "error", "detail": "Invalid JSON"}

    topic = data.get("topic")
    resource = data.get("resource")
    print(f"🔔 Notificación recibida: {topic} → {resource}")

    if topic == "orders" and resource.startswith("/orders/"):
        order_id = resource.split("/")[-1]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"https://api.mercadolibre.com{resource}",
                    headers={"Authorization": f"Bearer {get_ml_token()}"}
                )
            if response.status_code == 200:
                pedido = response.json()
                guardar_pedido_en_cache(pedido)
                print(f"✅ Pedido {order_id} guardado en caché")
            else:
                print(f"⚠️ Error consultando pedido {order_id}: {response.status_code}")
        except Exception as e:
            print(f"❌ Excepción al consultar pedido {order_id}: {e}")

    return {"status": "ok"}
