# database.py

import sqlite3
from datetime import datetime
from typing import Optional, Dict

DB_NAME = "pedidos.db"

def init_db():
    """
    Crea las tablas necesarias si no existen:
      - pedidos (con shipment_id, tipo_envio, usuario, etc.)
      - usuarios (id, username único, hashed_password)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1) Tabla 'pedidos'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        order_id       TEXT PRIMARY KEY,
        cliente        TEXT,
        titulo         TEXT,
        cantidad       INTEGER,
        estado         TEXT    DEFAULT 'pendiente',
        fecha_armado   TEXT,
        fecha_despacho TEXT,
        logistica      TEXT,
        shipment_id    TEXT,
        tipo_envio     TEXT,
        usuario        TEXT
    )
    """)

    # 2) Tabla 'usuarios'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT    UNIQUE NOT NULL,
        hashed_password TEXT    NOT NULL
    )
    """)
    conn.commit()
    conn.close()

# -------------------------------------------------------
# Funciones para CRUD de 'usuarios'
# -------------------------------------------------------

def create_user(username: str, hashed_password: str) -> bool:
    """
    Inserta un nuevo usuario con nombre de usuario y contraseña hasheada.
    Devuelve True si se creó, False si el username ya existía.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (username, hashed_password) VALUES (?, ?)",
            (username, hashed_password)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def get_user_by_username(username: str) -> Optional[Dict]:
    """
    Devuelve un diccionario con {'id', 'username', 'hashed_password'} si existe,
    o None si no existe.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, hashed_password FROM usuarios WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "hashed_password": row[2]}

# -------------------------------------------------------
# Funciones para CRUD de 'pedidos'
# -------------------------------------------------------

def add_order_if_not_exists(order_id, detalle):
    """
    Inserta el pedido en la tabla 'pedidos' si no existía ya.
    Se extrae título/cantidad de detalle["items"], y si detalle trae 'shipment_id',
    se graba en la nueva columna.
    """
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Si ya existe en la tabla, no se inserta de nuevo
    cursor.execute("SELECT 1 FROM pedidos WHERE order_id = ?", (order_id,))
    if cursor.fetchone() is None:
        items = detalle.get("items", [])
        if items:
            primer_item = items[0]
            titulo   = primer_item.get("titulo", "")
            cantidad = primer_item.get("cantidad", 0)
        else:
            titulo   = ""
            cantidad = 0

        cliente     = detalle.get("cliente", "Cliente desconocido")
        shipment_id = detalle.get("shipment_id")  # puede ser None

        cursor.execute(
            """
            INSERT INTO pedidos (
                order_id, cliente, titulo, cantidad, estado,
                logistica, shipment_id, tipo_envio, usuario
            )
            VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?)
            """,
            (
                order_id,
                cliente,
                titulo,
                cantidad,
                None,             # logistica al crear
                shipment_id,      # nuevo campo
                None,             # tipo_envio (se define al despachar)
                None              # usuario (se definirá al armar o despachar)
            )
        )

    conn.commit()
    conn.close()

def marcar_envio_armado(shipment_id: str, usuario: str) -> bool:
    """
    Cambia a 'armado' todas las filas de la tabla 'pedidos'
    cuyo shipment_id coincida con el valor dado. Devuelve True
    si al menos 1 fila fue actualizada.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE pedidos
        SET estado = 'armado',
            fecha_armado = ?,
            usuario = ?
        WHERE shipment_id = ?
        """,
        (datetime.now().isoformat(), usuario, shipment_id)
    )
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0

# database.py

def marcar_pedido_despachado(order_or_shipment_id: str, logistica: str, tipo_envio: Optional[str], usuario: Optional[str]) -> bool:
    """
    Actualiza el estado a 'despachado' usando order_id o shipment_id.
    Registra fecha_despacho, logistica, tipo_envio y usuario, solo si antes estaba 'armado'.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1) Buscamos fila por order_id o shipment_id
    cursor.execute(
        "SELECT order_id, estado FROM pedidos WHERE order_id = ? OR shipment_id = ?",
        (order_or_shipment_id, order_or_shipment_id)
    )
    fila = cursor.fetchone()
    if not fila:
        conn.close()
        return False

    order_id_encontrado, estado_actual = fila
    if estado_actual != "armado":
        conn.close()
        return False

    # 2) Actualizamos fila usando el order_id real
    ahora = datetime.now().isoformat()
    cursor.execute(
        """
        UPDATE pedidos
        SET estado = 'despachado',
            fecha_despacho = ?,
            logistica = ?,
            tipo_envio = ?,
            usuario = ?,
            shipment_id = ?
        WHERE order_id = ?
        """,
        (ahora, logistica, tipo_envio, usuario, order_or_shipment_id, order_id_encontrado)
    )
    filas_actualizadas = cursor.rowcount
    conn.commit()
    conn.close()
    return filas_actualizadas > 0

def get_all_pedidos(
    order_id: str      = None,
    shipment_id: str   = None,      # <--- añadimos este parámetro
    date_from:   str   = None,
    date_to:     str   = None,
    logistica:   str   = None
) -> list[dict]:
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    query  = """
        SELECT 
            order_id,
            cliente,
            titulo,
            cantidad,
            estado,
            fecha_armado,
            fecha_despacho,
            logistica,
            shipment_id,
            tipo_envio,
            usuario
        FROM pedidos
        WHERE 1=1
    """
    params = []

    if order_id:
        query += " AND order_id LIKE ?"
        params.append(f"%{order_id}%")
    if shipment_id:
        query += " AND shipment_id LIKE ?"
        params.append(f"%{shipment_id}%")
    if date_from:
        query += " AND (fecha_armado >= ? OR fecha_despacho >= ?)"
        params.extend([date_from, date_from])
    if date_to:
        query += " AND (fecha_armado <= ? OR fecha_despacho <= ?)"
        params.extend([date_to, date_to])
    if logistica:
        query += " AND logistica = ?"
        params.append(logistica)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    pedidos = []
    for row in rows:
        pedidos.append({
            "order_id":       row[0],
            "cliente":        row[1],
            "titulo":         row[2],
            "cantidad":       row[3],
            "estado":         row[4],
            "fecha_armado":   row[5],
            "fecha_despacho": row[6],
            "logistica":      row[7],
            "shipment_id":    row[8],
            "tipo_envio":     row[9],
            "usuario":        row[10]
        })
    return pedidos
