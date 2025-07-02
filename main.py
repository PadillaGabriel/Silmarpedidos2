
import logging
import os
import requests
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from passlib.hash import bcrypt
import cv2
import numpy as np
from sqlalchemy.orm import Session

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from database.models import Base, MLPedidoCache
from database.init import init_db
from ws.items import buscar_item_por_sku
from crud.usuarios import get_user_by_username, create_user
from crud.pedidos import (
    add_order_if_not_exists,
    marcar_envio_armado,
    marcar_pedido_despachado,
    get_all_pedidos,
    get_estado_envio
)

from sqlalchemy.engine.url import make_url
from crud.pedidos import buscar_item_cache_por_sku
from crud.logisticas import get_all_logisticas, add_logistica
from api_ml import get_order_details, enriquecer_items_ws
from ws.catalogo import  actualizar_ws_items

DATABASE_URL = os.getenv("DATABASE_URL")
url = make_url(DATABASE_URL)

if url.drivername.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

logger = logging.getLogger("uvicorn.error")
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


        
@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        logger.error("init_db falló: %s", e)

async def get_current_user(request: Request):
    user = request.session.get("username")
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return {"username": user}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    usuario = request.session.get("username")
    return templates.TemplateResponse("inicio.html", {"request": request, "usuario": usuario})

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if get_user_by_username(username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario ya existe")
    create_user(username, bcrypt.hash(password))
    request.session["username"] = username
    return RedirectResponse("/configuracion", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    user = get_user_by_username(username)
    if not user or not bcrypt.verify(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    request.session["username"] = username
    return RedirectResponse("/configuracion", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)
def obtener_info_adicional_por_sku(sku, db: Session):
    try:
        item = buscar_item_cache_por_sku(db, sku)
        if item:
            return {
                "codigo_proveedor": item.item_vendorCode,
                "codigo_alfa": item.item_code
            }
    except Exception as e:
        print("❌ Error buscando en cache:", e)
    return {"codigo_proveedor": None, "codigo_alfa": None}

@app.get("/actualizar-cache-ws", response_class=JSONResponse)
async def actualizar_cache_ws(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        actualizar_ws_items(db)
        return {"success": True, "mensaje": "Catálogo actualizado correctamente desde WS"}
    except Exception as e:
        return {"success": False, "error": str(e)}
        
@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_get(request: Request, current_user: dict = Depends(get_current_user)):
    logisticas = get_all_logisticas()
    return templates.TemplateResponse("configuracion.html", {"request": request, "usuario": current_user["username"], "logisticas": logisticas})

@app.post("/configuracion")
async def configuracion_post(request: Request, logistica: str = Form(...), current_user: dict = Depends(get_current_user)):
    add_logistica(logistica.strip())
    return RedirectResponse("/configuracion", status_code=302)

@app.get("/historial", response_class=HTMLResponse)
async def historial_get(request: Request, current_user: dict = Depends(get_current_user), estado: str = Query(None), shipment_id: str = Query(None), logistica: str = Query(None)):
    usuario = current_user["username"]
    pedidos = get_all_pedidos()
    filtrados = [p for p in pedidos if (not estado or estado == "Todos" or p["estado"] == estado.lower()) and
                                        (not shipment_id or shipment_id in (p["shipment_id"] or "")) and
                                        (not logistica or logistica == (p["logistica"] or ""))]
    return templates.TemplateResponse("historial.html", {
        "request": request,
        "usuario": usuario,
        "pedidos": filtrados,
        "filtro_estado": estado or "Todos",
        "filtro_shipment": shipment_id or "",
        "filtro_logistica": logistica or "",
    })

@app.get("/escanear", response_class=HTMLResponse)
async def escanear_get(request: Request, current_user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("escanear.html", {"request": request, "usuario": current_user["username"]})

@app.post("/escanear", response_class=JSONResponse)
async def escanear_post(
    request: Request,
    order_id: str = Form(None),
    shipment_id: str = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    detalle = await get_order_details(order_id=order_id, shipment_id=shipment_id, db=db)

    if detalle.get("cliente") == "Error" or not detalle.get("items"):
        return {"success": False, "error": "Pedido Cancelado"}

    # 🔧 Enriquecer ítems con datos del Web Service
    await enriquecer_items_ws(detalle["items"], db)

    # 💾 Guardar internamente si no existe
    if not any(p["shipment_id"] == shipment_id for p in get_all_pedidos(shipment_id=shipment_id)):
        primer_oid = detalle.get("primer_order_id")
        if primer_oid:
            mini = [
                {"order_id": primer_oid, "titulo": i["titulo"], "cantidad": i["cantidad"], "shipment_id": shipment_id}
                for i in detalle["items"]
            ]
            add_order_if_not_exists({"cliente": detalle["cliente"], "items": mini})

    return {"success": True, "detalle": detalle}


@app.post("/decode-qr", response_class=JSONResponse)
async def decode_qr(frame: UploadFile = File(...)):
    content = await frame.read()
    arr = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    if data:
        detalle = await escanear_post(request=None, order_id=None, shipment_id=data)
        return {"data": data, "detalle": detalle.get("detalle")}
    return {"data": None, "error": "QR no detectado"}

@app.post("/armar", response_class=JSONResponse)
async def armar_post(
    order_id: str = Form(None),
    shipment_id: str = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    usuario = current_user["username"]
    id_buscar = shipment_id or order_id
    if not id_buscar:
        return {"success": False, "error": "Falta ID"}

    # Verificar estado del envío en Mercado Libre
    token = os.getenv("ML_ACCESS_TOKEN")
    if token:
        try:
            url = f"https://api.mercadolibre.com/shipments/{id_buscar}"
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(url, headers=headers)
            if r.ok and r.json().get("status") == "cancelled":
                return {"success": False, "error": "El pedido fue cancelado. No se puede armar."}
        except Exception as e:
            return {"success": False, "error": f"Error consultando estado del envío: {e}"}

    # Verificar estado actual interno (local en la DB)
    estado_actual = get_estado_envio(id_buscar)
    if estado_actual == "armado":
        return {"success": False, "error": "Este pedido ya fue armado anteriormente."}
    if estado_actual == "despachado":
        return {"success": False, "error": "Este pedido ya fue despachado. No se puede volver a armar."}

    # Marcar como armado
    ok = marcar_envio_armado(id_buscar, usuario)
    return {"success": ok, "error": None if ok else "No se pudo marcar como armado"}
    
@app.get("/estado_envio", response_class=JSONResponse)
def estado_envio(shipment_id: str, current_user: dict = Depends(get_current_user)):
    return {"estado": get_estado_envio(shipment_id)}

@app.get("/despachar", response_class=HTMLResponse)
async def despachar_get(request: Request, current_user: dict = Depends(get_current_user)):
    logisticas = get_all_logisticas()
    return templates.TemplateResponse("despachar.html", {"request": request, "usuario": current_user["username"], "logisticas": logisticas})

@app.post("/despachar")
async def despachar_post(
    order_id: str = Form(None),
    shipment_id: str = Form(None),
    logistica: str = Form(...),
    tipo_envio: str = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    usuario = current_user["username"]
    id_buscar = shipment_id or order_id
    if not id_buscar:
        return {"success": False, "error": "Falta ID"}

    # Verificar estado del envío
    token = os.getenv("ML_ACCESS_TOKEN")
    if token:
        url = f"https://api.mercadolibre.com/shipments/{id_buscar}"
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers)
        if r.ok:
            data = r.json()
            if data.get("status") == "cancelled":
                return {"success": False, "error": "El pedido fue cancelado. No puede despacharse."}

    # ✅ Ya no se valida checklist
    ok = marcar_pedido_despachado(id_buscar, logistica, tipo_envio, usuario)
    return {"success": ok, "mensaje": "Pedido despachado correctamente" if ok else "No se pudo despachar"}
