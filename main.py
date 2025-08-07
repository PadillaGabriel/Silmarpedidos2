import os
import csv
import cv2
import numpy as np
import logging
import asyncio
import requests
import httpx
from fastapi import BackgroundTasks
from io import StringIO
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone, time
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from fastapi import (
    FastAPI, Request, Form, Depends, HTTPException, status, Query, File, UploadFile, APIRouter
)
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from passlib.hash import bcrypt

from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, or_


# Inicialización DB
from database.connection import SessionLocal
from database.init import init_db
from database.models import Base, MLPedidoCache,Pedido

# Autenticación
from auth_ml import get_ml_token, obtener_token

# CRUD
from crud.pedidos import (
    add_order_if_not_exists,
    marcar_envio_armado,
    marcar_pedido_despachado,
    get_all_pedidos,
    get_estado_envio,
    marcar_pedido_con_feedback
)
from crud.usuarios import get_user_by_username, create_user
from crud.logisticas import get_all_logisticas, add_logistica

# WS externos
from ws.items import buscar_item_por_sku
from ws.catalogo import actualizar_ws_items

# Lógica ML
from api_ml import fetch_api, get_order_details,parse_order_data, guardar_pedido_en_cache


# Webhooks
from webhooks import webhooks  # 👈 importa el router desde webhooks.py
from database.connection import get_db





logger = logging.getLogger("uvicorn.error")
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.include_router(webhooks, prefix="/webhooks")

db = SessionLocal()
router = APIRouter()

TTL_MIN = 10

def _enriquecer_bg(shipment_id: str):
    from database.connection import SessionLocal
    from database.models import MLPedidoCache
    db = SessionLocal()
    try:
        import asyncio
        # Trae y guarda/enriquece desde la API
        asyncio.run(get_order_details(shipment_id=shipment_id, db=db))

        # ⚠️ Puede haber varias filas con el mismo shipment_id (distintos order_id)
        recs = (db.query(MLPedidoCache)
                  .filter(MLPedidoCache.shipment_id == shipment_id)
                  .order_by(MLPedidoCache.fecha_consulta.desc())
                  .all())

        for rec in recs:
            if hasattr(rec, "is_enriched"):
                rec.is_enriched = True
            if hasattr(rec, "last_enriched_at"):
                rec.last_enriched_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as e:
        print(f"⚠️ Enriquecimiento falló para {shipment_id}: {e}")
        db.rollback()
    finally:
        db.close()
        
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
async def home(request: Request, db: Session = Depends(get_db)):
    usuario = request.session.get("username")
    resumen = resumen_dashboard(db)  # función que devuelve el resumen

    return templates.TemplateResponse("inicio.html", {
        "request": request,
        "usuario": usuario,
        **resumen  # esto pasa flex_armados, cancelados, etc.
    })

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


@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_get(request: Request, current_user: dict = Depends(get_current_user)):
    logisticas = get_all_logisticas(db)
    return templates.TemplateResponse("configuracion.html", {"request": request, "usuario": current_user["username"], "logisticas": logisticas})

@app.post("/configuracion")
async def configuracion_post(
    request: Request,
    logistica: str = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)  # ✅ agregar esta línea
):
    add_logistica(logistica.strip(), db)  # ✅ pasar db a la función
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
async def escanear_post(
    request: Request,
    order_id: str = Form(None),
    shipment_id: str = Form(None),
    background: BackgroundTasks = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if not order_id and not shipment_id:
            return JSONResponse(status_code=400, content={"success": False, "error": "Falta order_id o shipment_id"})

# 1) Si tengo shipment_id, intento Cache FIRST (multi-orden)
        if shipment_id:
            recs = (db.query(MLPedidoCache)
                    .filter(MLPedidoCache.shipment_id == shipment_id)
                    .order_by(MLPedidoCache.fecha_consulta.desc(), MLPedidoCache.id.desc())
                    .all())

            if recs:
                # merge de info
                items = []
                order_ids = []
                cliente = ""
                estado_envio = ""
                estado_ml = ""

                for r in recs:
                    if r.order_id: order_ids.append(r.order_id)
                    if not cliente and r.cliente: cliente = r.cliente
                    if not estado_envio and r.estado_envio: estado_envio = r.estado_envio
                    if not estado_ml and r.estado_ml: estado_ml = r.estado_ml
                    if r.detalle:
                        try:
                            items.extend(r.detalle)   # si ya guardás JSON en 'detalle'
                        except Exception:
                            pass

                order_ids = list(dict.fromkeys(order_ids))  # únicos, preservando orden

                detalle = {
                    "primer_shipment_id": shipment_id,
                    "order_ids": order_ids,           # 👈 todos los orders de ese envío
                    "cliente": cliente,
                    "estado_envio": estado_envio,
                    "estado_ml": estado_ml,
                    "items": items or []
                }

                # opcional: disparar enriquecimiento en bg
                if background:
                    background.add_task(_enriquecer_bg, shipment_id)

                return {"success": True, "detalle": detalle}


        # 2) No hay cache útil → usa flujo consolidado (resolverá shipment si entra solo order)
        detalle = await get_order_details(order_id=order_id, shipment_id=shipment_id, db=db)

        # Resuelve SID por si vino vacío
        sid = shipment_id or detalle.get("primer_shipment_id")

        # 3) Validaciones
        if detalle.get("cliente") == "Error" or not detalle.get("items"):
            estado_ml = detalle.get("estado_ml")
            msg = "Pedido cancelado" if (estado_ml == "cancelled") else "No se encontraron ítems para este pedido"
            return JSONResponse(status_code=404, content={"success": False, "error": msg, "shipment_id": sid, "order_id": order_id})

        # 4) Alta mínima en tu tabla de “pedidos a armar” si no existe
        #    (usando el SID resuelto para evitar None)
        try:
            sid_for_check = sid
            if sid_for_check and not any(p["shipment_id"] == sid_for_check for p in get_all_pedidos(shipment_id=sid_for_check)):
                primer_oid = detalle.get("primer_order_id")
                if primer_oid:
                    mini = [
                        {"order_id": primer_oid, "titulo": i["titulo"], "cantidad": i["cantidad"], "shipment_id": sid_for_check}
                        for i in detalle["items"]
                    ]
                    add_order_if_not_exists({"cliente": detalle["cliente"], "items": mini})
        except Exception as e:
            # No bloquees el flujo si falla el alta mínima
            print(f"⚠️ No se pudo preparar alta mínima en 'pedidos': {e}")

        # 5) Enriquecer en background si todavía no hay cache enriquecida
        if sid and background:
            background.add_task(_enriquecer_bg, sid)

        return {"success": True, "detalle": detalle}

    except Exception as e:
        print(f"❌ /escanear error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": "Error interno"})


# main.py — reemplazá /decode-qr
@app.post("/decode-qr", response_class=JSONResponse)
async def decode_qr(frame: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await frame.read()
    arr = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

    if not data:
        return {"data": None, "error": "QR no detectado"}

    # Igual que /escanear, pero directo:
    detalle = await get_order_details(shipment_id=data, db=db)
    if detalle.get("cliente") == "Error" or not detalle.get("items"):
        return {"data": data, "error": "No se encontraron ítems para este pedido", "detalle": None}

    return {"data": data, "detalle": detalle}

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
async def despachar_get(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)  # 👈 faltaba inyectar db
):
    logisticas = get_all_logisticas(db)
    return templates.TemplateResponse(
        "despachar.html",
        {"request": request, "usuario": current_user["username"], "logisticas": logisticas}
    )


# --- POST: siempre JSON ---
@app.post("/despachar")
async def despachar_post(
    shipment_id: str = Form(...),
    logistica: str = Form(...),
    tipo_envio: str = Form(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    usuario = current_user["username"]

    try:
        # 1) Validar cancelado en cache local
        pedido_cache = (
            db.query(MLPedidoCache)
              .filter(
                  MLPedidoCache.shipment_id == shipment_id,
                  MLPedidoCache.estado_ml == "cancelled"
              )
              .first()
        )
        if pedido_cache:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": f"El envío está cancelado (local). order_id={pedido_cache.order_id}"}
            )

        # 2) Validar cancelado en API de ML (opcional si hay token)
        token = os.getenv("ML_ACCESS_TOKEN")
        if token:
            try:
                url = f"https://api.mercadolibre.com/shipments/{shipment_id}"
                headers = {"Authorization": f"Bearer {token}"}
                r = requests.get(url, headers=headers, timeout=8)
                if r.ok:
                    data = r.json()
                    if data.get("status") == "cancelled":
                        return JSONResponse(
                            status_code=409,
                            content={"success": False, "error": "El envío está cancelado (API de ML)."}
                        )
            except requests.RequestException as e:
                # No bloqueamos el despacho por un fallo de red; solo registramos
                print(f"⚠️ No se pudo validar en ML: {e}")

        # 3) Ejecutar despacho
        ok = marcar_pedido_despachado(db, shipment_id, logistica, tipo_envio, usuario)

        if not ok:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No se pudo despachar. Verificá que todos los ítems estén armados."}
            )

        return JSONResponse(
            status_code=200,
            content={"success": True, "mensaje": "Envío despachado correctamente"}
        )

    except Exception as e:
        db.rollback()  # 👈 por si algo falló después de tocar DB
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
    
    
@router.get("/dashboard/resumen")
def resumen_dashboard(db: Session = Depends(get_db)):
    ahora = datetime.now(timezone.utc)
    hoy = ahora.date()

    # Ventana: de ayer 14:00 a hoy 14:00 (UTC)
    inicio = datetime.combine(hoy - timedelta(days=1), time(14, 0)).astimezone(timezone.utc)
    fin    = datetime.combine(hoy,                 time(14, 0)).astimezone(timezone.utc)

    print("🧪 Ventana de conteo:", inicio.isoformat(), "→", fin.isoformat())

    # 🚫 Excluir FULL (fulfillment) en todas las consultas
    no_full = (MLPedidoCache.logistic_type != 'fulfillment')

    # === FLEX: self_service ===
    flex_base = (
        db.query(MLPedidoCache.shipment_id)
          .filter(
              MLPedidoCache.estado_ml != 'cancelled',
              MLPedidoCache.fecha_consulta.between(inicio, fin),
              MLPedidoCache.logistic_type == 'self_service',
              no_full
          )
          .distinct()
    )

    # Total de shipments únicos que NO están armados
    flex_total = (
        flex_base
        .outerjoin(Pedido, MLPedidoCache.shipment_id == Pedido.shipment_id)
        .filter(or_(Pedido.estado == None, Pedido.estado != 'armado'))
        .count()
    )

    # Shipments armados
    flex_armados = (
        db.query(func.count(distinct(Pedido.shipment_id)))
          .join(MLPedidoCache, MLPedidoCache.shipment_id == Pedido.shipment_id)
          .filter(
              Pedido.estado == 'armado',
              Pedido.fecha_armado.between(inicio, fin),
              MLPedidoCache.logistic_type == 'self_service',
              no_full
          )
          .scalar()
    )

    # === COLECTA: cross_docking ===
    colecta_base = (
        db.query(MLPedidoCache.shipment_id)
          .filter(
              MLPedidoCache.estado_ml != 'cancelled',
              MLPedidoCache.fecha_consulta.between(inicio, fin),
              MLPedidoCache.logistic_type == 'cross_docking',
              no_full
          )
          .distinct()
    )

    colecta_total = (
        colecta_base
        .outerjoin(Pedido, MLPedidoCache.shipment_id == Pedido.shipment_id)
        .filter(or_(Pedido.estado == None, Pedido.estado != 'armado'))
        .count()
    )

    colecta_armados = (
        db.query(func.count(distinct(Pedido.shipment_id)))
          .join(MLPedidoCache, MLPedidoCache.shipment_id == Pedido.shipment_id)
          .filter(
              Pedido.estado == 'armado',
              Pedido.fecha_armado.between(inicio, fin),
              MLPedidoCache.logistic_type == 'cross_docking',
              no_full
          )
          .scalar()
    )

    # Cancelados (por shipment) — también excluimos FULL
    cancelados = (
        db.query(distinct(MLPedidoCache.shipment_id))
          .filter(
              MLPedidoCache.estado_ml == 'cancelled',
              MLPedidoCache.fecha_consulta.between(inicio, fin),
              no_full
          )
          .all()
    )
    cancelados_ids = [r[0] for r in cancelados]

    return {
        "flex_total": flex_total,
        "flex_armados": flex_armados,
        "colecta_total": colecta_total,
        "colecta_armados": colecta_armados,
        "cancelados": cancelados_ids
    }