from sqlalchemy.orm import Session
from database.models import Logistica

def get_all_logisticas(db: Session):
    return [l.nombre for l in db.query(Logistica).order_by(Logistica.nombre).all()]

def add_logistica(nombre: str, db: Session):
    if db.query(Logistica).filter_by(nombre=nombre).first():
        return False
    db.add(Logistica(nombre=nombre))
    db.commit()
    return True
