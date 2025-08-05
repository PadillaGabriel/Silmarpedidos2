from sqlalchemy.orm import Session
from database.models import WsItem

def buscar_item_cache_por_sku(db: Session, sku: str):
    return db.query(WsItem).filter(WsItem.item_code == sku).first()
