
import logging
import os
import requests
import csv
import re
from crud.pedidos import guardar_pedido_en_cache

from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query, File, UploadFile, APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from passlib.hash import bcrypt
import cv2
import numpy as np
from sqlalchemy.orm import Session
from urllib.parse import urlencode
from io import StringIO
import httpx
from auth_ml import get_ml_token
from database.connection import SessionLocal  # ✅ Correcto
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from auth_ml import obtener_token
from crud.pedidos import guardar_pedido_en_cache
from utils import fetch_api

from database.models import Base, MLPedidoCache
from database.init import init_db
from ws.items import buscar_item_por_sku
from crud.usuarios import get_user_by_username, create_user
from crud.pedidos import (
    add_order_if_not_exists,
    marcar_envio_armado,
    marcar_pedido_despachado,
    get_all_pedidos,
    get_estado_envio,
    marcar_pedido_con_feedback
)
from webhooks import webhooks 
from crud.pedidos import buscar_item_cache_por_sku
from crud.logisticas import get_all_logisticas, add_logistica
from api_ml import get_order_details, enriquecer_items_ws
from ws.catalogo import  actualizar_ws_items


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
app.include_router(webhooks, prefix="/webhooks")

db = SessionLocal()
router = APIRouter()

        
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
        request.session["error"] = "El usuario ya existe"
        return RedirectResponse("/register", status_code=302)

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
        request.session["error"] = "Credenciales inválidas"
        return RedirectResponse("/login", status_code=302)

    request.session["username"] = username
    return RedirectResponse("/configuracion", status_code=302)

@app.post("/clear_error")
async def clear_error(request: Request):
    request.session.pop("error", None)
    return {"ok": True}


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

@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_get(request: Request, current_user: dict = Depends(get_current_user)):
    logisticas = get_all_logisticas()
    return templates.TemplateResponse("configuracion.html", {"request": request, "usuario": current_user["username"], "logisticas": logisticas})

@app.post("/configuracion")
async def configuracion_post(request: Request, logistica: str = Form(...), current_user: dict = Depends(get_current_user)):
    add_logistica(logistica.strip())
    return RedirectResponse("/configuracion", status_code=302)
@app.post("/configuracion")
async def configuracion_post(
    request: Request,
    logistica: str = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    add_logistica(db, logistica.strip())
    return RedirectResponse("/configuracion", status_code=302)

@app.get("/recuperar", response_class=HTMLResponse)
async def recuperar_get(request: Request):
    return templates.TemplateResponse("recuperar.html", {"request": request})

@app.post("/recuperar")
async def recuperar_post(
    request: Request,
    username: str = Form(...),
    clave_maestra: str = Form(...),
    nueva_password: str = Form(...)
):
    if clave_maestra != "silmarreset2024":
        request.session["error"] = "Clave maestra incorrecta"
        return RedirectResponse("/recuperar", status_code=302)

    user = get_user_by_username(username)
    if not user:
        request.session["error"] = "Usuario no encontrado"
        return RedirectResponse("/recuperar", status_code=302)

    user.hashed_password = bcrypt.hash(nueva_password)
    db = SessionLocal()
    db.add(user)
    db.commit()
    db.close()

    request.session["username"] = username
    return RedirectResponse("/configuracion", status_code=302)

@app.get("/historial/exportar")
async def exportar_csv(
    request: Request,
    current_user: dict = Depends(get_current_user),
    estado: str = Query(None),
    order_id: str = Query(None),
    logistica: str = Query(None),
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
):
    def parse_fecha(fecha_str):
        try:
            return datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except:
            return None

    desde = parse_fecha(fecha_desde)
    hasta = parse_fecha(fecha_hasta)
    pedidos = get_all_pedidos()

    filtrados = []
    for p in pedidos:
        cumple_estado = not estado or estado == "Todos" or p["estado"] == estado.lower()
        cumple_order_id = not order_id or order_id in str(p["order_id"])
        cumple_logistica = not logistica or logistica == (p["logistica"] or "")

        fecha_pedido = None
        if p.get("fecha_despacho"):
            try:
                fecha_pedido = datetime.strptime(p["fecha_despacho"], "%Y-%m-%d").date()
            except:
                pass

        cumple_fecha = True
        if desde and fecha_pedido:
            cumple_fecha = cumple_fecha and (fecha_pedido >= desde)
        if hasta and fecha_pedido:
            cumple_fecha = cumple_fecha and (fecha_pedido <= hasta)

        if cumple_estado and cumple_order_id and cumple_logistica and cumple_fecha:
            filtrados.append(p)

    # Escribimos el CSV en memoria
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID", "Cliente", "Título", "Cantidad", "Estado",
        "Fecha Despacho", "Logística", "Usuario Armado", "Usuario Despacho"
    ])
    for p in filtrados:
        writer.writerow([
            p["order_id"],
            p["cliente"],
            p["titulo"],
            p["cantidad"],
            p["estado"],
            p.get("fecha_despacho") or "—",
            p.get("logistica") or "—",
            p.get("usuario_armado") or "-",
            p.get("usuario_despacho") or "—"
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=historial_pedidos.csv"}
    )


@app.get("/historial", response_class=HTMLResponse)
async def historial_get(
    request: Request,
    current_user: dict = Depends(get_current_user),
    estado: str = Query(None),
    order_id: str = Query(None),
    logistica: str = Query(None),
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    page: int = Query(1)
):
    usuario = current_user["username"]
    pedidos = get_all_pedidos()

    def parse_fecha(fecha_str):
        try:
            return datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except:
            return None

    desde = parse_fecha(fecha_desde)
    hasta = parse_fecha(fecha_hasta)

    filtrados = []
    for p in pedidos:
        cumple_estado = not estado or estado == "Todos" or p["estado"] == estado.lower()
        cumple_order_id = not order_id or order_id in str(p["order_id"])
        cumple_logistica = not logistica or logistica == (p["logistica"] or "")

        fecha_pedido = None
        if p.get("fecha_despacho"):
            try:
                fecha_pedido = datetime.strptime(p["fecha_despacho"], "%Y-%m-%d").date()
            except:
                pass

        cumple_fecha = True
        if desde and fecha_pedido:
            cumple_fecha = cumple_fecha and (fecha_pedido >= desde)
        if hasta and fecha_pedido:
            cumple_fecha = cumple_fecha and (fecha_pedido <= hasta)

        if cumple_estado and cumple_order_id and cumple_logistica and cumple_fecha:
            filtrados.append(p)

    PAGE_SIZE = 20
    total = len(filtrados)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    inicio = (page - 1) * PAGE_SIZE
    fin = inicio + PAGE_SIZE
    pagina_actual = filtrados[inicio:fin]

    # Armado de URLs de paginación segura
    query_params = dict(request.query_params)

    siguiente_url = None
    if page < total_pages:
        query_params["page"] = page + 1
        siguiente_url = f"?{urlencode(query_params)}"

    anterior_url = None
    if page > 1:
        query_params["page"] = page - 1
        anterior_url = f"?{urlencode(query_params)}"

    return templates.TemplateResponse("historial.html", {
        "request": request,
        "usuario": usuario,
        "pedidos": pagina_actual,
        "filtro_estado": estado or "Todos",
        "filtro_order_id": order_id or "",
        "filtro_logistica": logistica or "",
        "filtro_fecha_desde": fecha_desde or "",
        "filtro_fecha_hasta": fecha_hasta or "",
        "pagina_actual": page,
        "total_paginas": total_pages,
        "siguiente_url": siguiente_url,
        "anterior_url": anterior_url,
    })
@app.get("/escanear", response_class=HTMLResponse)
async def escanear_get(request: Request, current_user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("escanear.html", {"request": request, "usuario": current_user["username"]})

@app.post("/escanear", response_class=JSONResponse)
async def escanear_post(request: Request, order_id: str = Form(None), shipment_id: str = Form(None), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    detalle = await get_order_details(order_id=order_id, shipment_id=shipment_id, db=db)

    if detalle.get("cliente") == "Error" or not detalle.get("items"):
        return {"success": False, "error": "Pedido Cancelado"}

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
    logisticas = get_all_logisticas(db)
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





@router.post("/webhooks/ml")
async def recibir_webhook_ml(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        topic = body.get("topic")
        resource = body.get("resource")
        user_id = body.get("user_id")

        if not topic or not resource:
            return {"status": "ignored", "reason": "Missing topic or resource"}

        print(f"🔔 Notificación recibida: {topic} → {resource}")

        # Procesar solo pedidos nuevos o actualizados
        if topic == "orders_v2" and resource.startswith("/orders/"):
            order_id = resource.split("/")[-1]
            token = obtener_token()
            if not token:
                return {"status": "error", "reason": "No valid token"}

            # Llamamos a la API de ML
            pedido = fetch_api(f"/orders/{order_id}", extra_headers={"Authorization": f"Bearer {token}"})
            if pedido:
                await guardar_pedido_en_cache(pedido, db)

        return {"status": "ok"}
    
    except Exception as e:
        print(f"❌ Error en webhook ML: {e}")
        return {"status": "error", "detail": str(e)}