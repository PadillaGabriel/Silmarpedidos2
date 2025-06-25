from ws.auth import autenticar_desde_json
from ws.items import obtener_todos_los_items, parsear_items
from database.models import WsItem
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import os

# Crear carpeta de logs si no existe
os.makedirs("logs", exist_ok=True)
log_file = f"logs/catalogo_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def actualizar_ws_items(db: Session):
    print("🔄 Iniciando actualización del catálogo desde Web Service...")
    token = autenticar_desde_json()
    xml = obtener_todos_los_items(token)

    if not xml or not xml.strip().startswith("<"):
        print("❌ El XML devuelto es inválido o vacío.")
        logging.error("El XML devuelto es inválido o vacío.")
        return

    try:
        items = parsear_items(xml)
    except Exception as e:
        print("❌ Error al parsear XML:", e)
        logging.error(f"Error al parsear XML: {e}")
        return

    print(f"📦 {len(items)} ítems obtenidos. Procesando...")

    nuevos = []
    actualizados = 0

    for idx, data in enumerate(items):
        existente = db.get(WsItem, data["item_id"])
        if existente:
            existente.item_code = data["item_code"]
            existente.item_vendorCode = data["item_vendorCode"]
            existente.actualizado = datetime.utcnow()
            actualizados += 1
        else:
            nuevos.append(WsItem(
                item_id=data["item_id"],
                item_code=data["item_code"],
                item_vendorCode=data["item_vendorCode"]
            ))

        if idx > 0 and idx % 500 == 0:
            print(f"🔁 {idx}/{len(items)} procesados...")

    if nuevos:
        db.bulk_save_objects(nuevos)
    db.commit()

    print(f"✅ Catálogo actualizado: {len(nuevos)} nuevos, {actualizados} actualizados.")
    logging.info(f"Catálogo actualizado: {len(nuevos)} nuevos, {actualizados} actualizados.")

if __name__ == "__main__":
    from database.init import init_db
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    import os

    from dotenv import load_dotenv
    load_dotenv()

    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()
    try:
        actualizar_ws_items(db)
    finally:
        db.close()

