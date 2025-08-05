# crud/utils_ml.py
import asyncio
from datetime import datetime, timezone
import aiohttp
import logging
from ws.items import obtener_todos_los_items, parsear_items
from auth_ml import  autenticar_desde_json
from database.models import MLItem, WsItem
from sqlalchemy.orm import Session

# Logger
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def enriquecer_permalinks(items: list, token: str, db: Session):
    async with aiohttp.ClientSession() as session:
        tareas = []
        for item in items:
            item_id = item.get("item_id")
            if item_id:
                tareas.append(fetch_item_permalink(session, item_id, token, db))

        resultados = await asyncio.gather(*tareas)

        # Asignar resultados a los items originales
        permalink_map = {item_id: permalink for item_id, permalink in resultados}
        for item in items:
            item_id = item.get("item_id")
            item["permalink"] = permalink_map.get(item_id)

async def fetch_item_permalink(session, item_id, token, db):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                permalink = data.get("permalink")

                # Guardar en cache si existe el item
                item_db = db.query(MLItem).filter_by(item_id=item_id).first()
                if item_db:
                    item_db.permalink = permalink
                    item_db.actualizado = datetime.now(timezone.utc)
                else:
                    item_db = MLItem(
                        item_id=item_id,
                        permalink=permalink,
                        actualizado=datetime.now(timezone.utc)
                    )
                    db.add(item_db)
                db.commit()


                return item_id, permalink
    except Exception as e:
        logger.warning("Error al consultar item_id=%s: %s", item_id, e)
    return item_id, None
    
