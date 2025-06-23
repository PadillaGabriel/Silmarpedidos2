from database.connection import Session
from database.models import Logistica

def get_all_logisticas():
    session = Session()
    nombres = [l.nombre for l in session.query(Logistica).order_by(Logistica.nombre).all()]
    session.close()
    return nombres

def add_logistica(nombre):
    session = Session()
    if session.query(Logistica).filter_by(nombre=nombre).first():
        session.close()
        return False
    session.add(Logistica(nombre=nombre))
    session.commit()
    session.close()
    return True
