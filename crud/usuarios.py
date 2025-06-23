from database.connection import Session
from database.models import Usuario

def create_user(username, hashed_password):
    session = Session()
    session.add(Usuario(username=username, hashed_password=hashed_password))
    session.commit()
    session.close()

def get_user_by_username(username):
    session = Session()
    user = session.query(Usuario).filter_by(username=username).first()
    session.close()
    return user
