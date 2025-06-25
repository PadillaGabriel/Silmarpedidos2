from database.connection import SessionLocal
from database.models import Usuario

def create_user(username, hashed_password):
    session = SessionLocal()
    session.add(Usuario(username=username, hashed_password=hashed_password))
    session.commit()
    session.close()

def get_user_by_username(username):
    session = SessionLocal()
    user = session.query(Usuario).filter_by(username=username).first()
    session.close()
    return user
