from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, UniqueConstraint, Boolean, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()
engine = create_engine("sqlite:///pedidos.db", echo=False)
Session = sessionmaker(bind=engine)

class Pedido(Base):
    __tablename__ = "pedidos"
    id = Column(Integer, primary_key=True)
    order_id = Column(String(255))
    cliente = Column(String(255))
    titulo = Column(Text)
    cantidad = Column(Integer)
    estado = Column(String(50), default="pendiente")
    fecha_armado = Column(DateTime, nullable=True)
    fecha_despacho = Column(DateTime, nullable=True)
    logistica = Column(String(100), nullable=True)
    shipment_id = Column(String(255))
    tipo_envio = Column(String(100), nullable=True)
    usuario_armado = Column(String(100), nullable=True)
    usuario_despacho = Column(String(100), nullable=True)

    __table_args__ = (UniqueConstraint("shipment_id", "order_id", name="uix_shipment_order"),)

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

class Logistica(Base):
    __tablename__ = "logisticas"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), unique=True, nullable=False)

class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id = Column(Integer, primary_key=True)
    shipment_id = Column(String, nullable=False)
    item_id = Column(String, nullable=False)
    marcado = Column(Boolean, default=False)
    creado = Column(DateTime, default=datetime.utcnow)

class WsItem(Base):
    __tablename__ = "ws_items_cache"

    item_id = Column(String, primary_key=True)
    item_code = Column(String, index=True)
    item_vendorCode = Column("item_vendorcode", String)  # 👈 mapeo correcto
    actualizado = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)