import logging
import psycopg2

from passlib.hash import bcrypt
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
    get_all_pedidos,
    get_all_logisticas,
    add_logistica,
    get_user_by_username,
    create_user,
    get_connection
)
from api_ml import get_order_details


logger = logging.getLogger("uvicorn.error")
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Al arrancar la app, crea las tablas necesarias si no existen
init_db()

async def get_current_user(request: Request):
    user = request.session.get("username")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    return {"username": user}

# ——— Rutas de registro, login y logout ———

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
    if get_user_by_username(username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario ya existe")
    pwd_hash = bcrypt.hash(password)
    create_user(username, pwd_hash)
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
    user = get_user_by_username(username)
    if not user or not bcrypt.verify(password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    request.session["username"] = username
    if "logisticas" not in request.session:
        request.session["logisticas"] = []
    return RedirectResponse("/configuracion", status_code=status.HTTP_302_FOUND)

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("username", None)
    request.session.pop("logisticas", None)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

# ——— Página principal ———

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    usuario = request.session.get("username")
    return templates.TemplateResponse("inicio.html", {"request": request, "usuario": usuario})

# ——— Configuración de logísticas ———

@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_get(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    usuario    = current_user["username"]
    logisticas = get_all_logisticas()       # lee TODAS las logísticas de la tabla
    return templates.TemplateResponse(
        "configuracion.html",
        {
            "request":    request,
            "usuario":    usuario,
            "logisticas": logisticas
        }
    )

@app.post("/configuracion")
async def configuracion_post(
    request: Request,
    logistica: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    add_logistica(logistica.strip())        # inserta en la tabla global de logísticas
    return RedirectResponse("/configuracion", status_code=status.HTTP_302_FOUND)

# ——— Historial de pedidos ———

@app.get("/historial", response_class=HTMLResponse)
async def historial_get(
    request: Request,
    current_user: dict = Depends(get_current_user),
    estado: str | None = Query(None),
    shipment_id: str | None = Query(None),
    logistica: str | None = Query(None),
):
    usuario = current_user["username"]
    todos    = get_all_pedidos()
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

# ——— Escanear pedido ———

@app.get("/escanear", response_class=HTMLResponse)
async def escanear_get(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    usuario = current_user["username"]
    return templates.TemplateResponse("escanear.html", {"request": request, "usuario": usuario})

@app.post("/escanear", response_class=JSONResponse)
async def escanear_post(
    request: Request,
    order_id: str | None = Form(None),
    shipment_id: str | None = Form(None),
    current_user: dict = Depends(get_current_user)
):
    detalle = get_order_details(order_id=order_id, shipment_id=shipment_id)
    if detalle.get("cliente") == "Error" or not detalle.get("items"):
        return JSONResponse({"success": False, "error": "No se encontraron productos para ese pedido"})
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pedidos WHERE shipment_id = %s LIMIT 1", (shipment_id,))
    ya_existe = cursor.fetchone() is not None
    conn.close()
    if not ya_existe:
        primer_oid = detalle.get("primer_order_id")
        if primer_oid:
            mini = [{"order_id": primer_oid, "titulo": i["titulo"], "cantidad": i["cantidad"], "shipment_id": shipment_id} for i in detalle["items"]]
            add_order_if_not_exists(primer_oid, {"cliente": detalle["cliente"], "items": mini})
    return JSONResponse({"success": True, "detalle": detalle})

# ——— Marcar como armado ———

@app.post("/armar", response_class=JSONResponse)
async def armar_post(
    order_id: str | None = Form(None),
    shipment_id: str | None = Form(None),
    current_user: dict = Depends(get_current_user)
):
    usuario   = current_user["username"]
    id_buscar = shipment_id or order_id
    if not id_buscar:
        raise HTTPException(status_code=400, detail="Falta order_id o shipment_id")

    print("DEBUG armar_post ➔ llegó a /armar con shipment_id =", id_buscar, "y usuario =", usuario)
    ok = marcar_envio_armado(id_buscar, usuario)
    if ok:
        return {"success": True}
    return {
        "success": False,
        "error": "No se pudo marcar como armado (quizá ya estaba armado o no se escaneó antes)"
    }

# ——— Obtener estado de un shipment ———

@app.get("/estado_envio", response_class=JSONResponse)
def estado_envio(
    shipment_id: str,
    current_user: dict = Depends(get_current_user)
):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT estado FROM pedidos WHERE shipment_id = %s LIMIT 1", (shipment_id,))
    fila = cursor.fetchone()
    conn.close()
    if fila:
        return {"estado": fila[0]}
    return {"estado": None}

# ——— Despachar pedido ———

@app.get("/despachar", response_class=HTMLResponse)
async def despachar_get(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    usuario    = current_user["username"]
    logisticas = get_all_logisticas()       # leemos TODAS las logísticas para el select
    return templates.TemplateResponse(
        "despachar.html",
        {
            "request":    request,
            "usuario":    usuario,
            "logisticas": logisticas
        },
    )

@app.post("/despachar", response_class=JSONResponse)
def despachar_post(
    order_id: str | None = Form(None),
    shipment_id: str | None = Form(None),
    logistica: str    = Form(...),
    tipo_envio: str   = Form(...),
    current_user: dict = Depends(get_current_user)
):
    usuario   = current_user["username"]
    id_buscar = shipment_id or order_id
    if not id_buscar:
        raise HTTPException(status_code=400, detail="Falta ID de pedido")

    ok = marcar_pedido_despachado(id_buscar, logistica, tipo_envio, usuario)
    if ok:
        return {"success": True, "mensaje": "Pedido despachado correctamente"}
    return {"success": False, "error": "No se pudo despachar (¿no estaba armado?)"}
