import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from database import (
    init_db,
    add_order_if_not_exists,
    marcar_envio_armado,
    marcar_pedido_despachado,
    get_all_pedidos
)
from api_ml import get_order_details

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="tu_clave_super_secreta")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

init_db()

async def get_current_user(request: Request):
    user = request.session.get("username")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    return {"username": user}

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    usuario = request.session.get("username")
    return templates.TemplateResponse("register.html", {"request": request, "usuario": usuario})

@app.post("/register")
async def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    request.session["username"] = username
    request.session["logisticas"] = []
    return RedirectResponse("/configuracion", status_code=status.HTTP_302_FOUND)

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    usuario = request.session.get("username")
    return templates.TemplateResponse("login.html", {"request": request, "usuario": usuario})

@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    request.session["username"] = username
    if "logisticas" not in request.session:
        request.session["logisticas"] = []
    return RedirectResponse("/configuracion", status_code=status.HTTP_302_FOUND)

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("username", None)
    request.session.pop("logisticas", None)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    usuario = request.session.get("username")
    return templates.TemplateResponse("inicio.html", {"request": request, "usuario": usuario})

@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_get(request: Request, current_user: dict = Depends(get_current_user)):
    usuario = current_user["username"]
    logisticas = request.session.get("logisticas", [])
    return templates.TemplateResponse(
        "configuracion.html",
        {
            "request": request,
            "usuario": usuario,
            "logisticas": logisticas
        }
    )

@app.post("/configuracion")
async def configuracion_post(
    request: Request,
    logistica: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    usuario = current_user["username"]
    lista = request.session.get("logisticas", [])
    if logistica not in lista:
        lista.append(logistica)
        request.session["logisticas"] = lista
    return RedirectResponse("/configuracion", status_code=status.HTTP_302_FOUND)

@app.get("/historial", response_class=HTMLResponse)
async def historial_get(
    request: Request,
    current_user: dict = Depends(get_current_user),
    estado: str | None = Query(None),
    shipment_id: str | None = Query(None),
    logistica: str | None = Query(None),
):
    usuario = current_user["username"]
    todos = get_all_pedidos()
    filtrados = []
    for p in todos:
        if estado and estado != "Todos":
            if p["estado"] != estado.lower():
                continue
        if shipment_id:
            if shipment_id not in (p["shipment_id"] or ""):
                continue
        if logistica:
            if logistica != (p["logistica"] or ""):
                continue
        filtrados.append(p)
    return templates.TemplateResponse(
        "historial.html",
        {
            "request":          request,
            "usuario":          usuario,
            "pedidos":          filtrados,
            "filtro_estado":    estado or "Todos",
            "filtro_shipment":  shipment_id or "",
            "filtro_logistica": logistica or "",
        },
    )

@app.get("/escanear", response_class=HTMLResponse)
async def escanear_get(request: Request, current_user: dict = Depends(get_current_user)):
    usuario = current_user["username"]
    return templates.TemplateResponse(
        "escanear.html",
        {"request": request, "usuario": usuario}
    )

@app.post("/escanear", response_class=JSONResponse)
async def escanear_post(
    request: Request,
    order_id: str | None = Form(None),
    shipment_id: str | None = Form(None)
):
    detalle = get_order_details(order_id=order_id, shipment_id=shipment_id)
    if detalle.get("cliente") == "Error" or not detalle.get("items"):
        return JSONResponse({"success": False, "error": "No se encontraron productos para ese pedido"})
    for item in detalle["items"]:
        oid = item.get("order_id")
        if not oid:
            continue
        mini_detalle = {
            "cliente": detalle["cliente"],
            "items": [
                {
                    "order_id":    item.get("order_id"),
                    "titulo":      item.get("titulo"),
                    "cantidad":    item.get("cantidad"),
                    "shipment_id": item.get("shipment_id")
                }
            ]
        }
        add_order_if_not_exists(oid, mini_detalle)
    return JSONResponse({"success": True, "detalle": detalle})

@app.post("/armar", response_class=JSONResponse)
async def armar_post(
    shipment_id: str | None = Form(None),
    current_user: dict = Depends(get_current_user)
):
    usuario_actual = current_user["username"]
    if not shipment_id:
        return JSONResponse(
            {"success": False, "error": "Falta shipment_id para marcar armado."},
            status_code=400
        )
    ok = marcar_envio_armado(shipment_id, usuario_actual)
    if ok:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "No se pudo marcar como armado o ya estaba armado."})

@app.get("/despachar", response_class=HTMLResponse)
async def despachar_get(request: Request, current_user: dict = Depends(get_current_user)):
    usuario = current_user["username"]
    logisticas_seleccionadas = request.session.get("logisticas", [])
    return templates.TemplateResponse(
        "despachar.html",
        {
            "request": request,
            "usuario": usuario,
            "logisticas": logisticas_seleccionadas,
        },
    )

@app.post("/despachar", response_class=JSONResponse)
def despachar_post(
    order_id: str | None = Form(None),
    shipment_id: str | None = Form(None),
    logistica: str = Form(...),
    tipo_envio: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    usuario = current_user["username"]
    id_buscar = shipment_id or order_id
    if not id_buscar:
        raise HTTPException(status_code=400, detail="Falta ID de pedido")
    ok = marcar_pedido_despachado(id_buscar, logistica, tipo_envio, usuario)
    if ok:
        return {"success": True, "mensaje": "Pedido despachado correctamente"}
    return {"success": False, "error": "No se pudo despachar (¿está armado?)"}
