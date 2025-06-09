# database.py

import psycopg2
from psycopg2 import sql
import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger("uvicorn.error")


def get_connection():
    """
    Abre una conexión a PostgreSQL usando valores literales.
    Si prefieres variables de entorno, reemplaza aquí por os.getenv("DB_HOST"), etc.
    """
    return psycopg2.connect(
        host="192.168.10.136",
        port="5433",
        user="usuario_app",
        password="ContrasenaSegura",
        dbname="pedidos_app"
    )


def init_db():
    """
    Crea las tablas necesarias en PostgreSQL si no existen:
      - pedidos
      - usuarios
      - logisticas
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Tabla 'pedidos'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        id SERIAL PRIMARY KEY,
        order_id VARCHAR(255),
        cliente VARCHAR(255),
        titulo TEXT,
        cantidad INTEGER,
        estado VARCHAR(50) DEFAULT 'pendiente',
        fecha_armado TIMESTAMP NULL,
        fecha_despacho TIMESTAMP NULL,
        logistica VARCHAR(100) NULL,
        shipment_id VARCHAR(255),
        tipo_envio VARCHAR(100) NULL,
        usuario VARCHAR(100) NULL,
        UNIQUE(shipment_id, order_id)
    );
    """)

    # Tabla 'usuarios'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        hashed_password VARCHAR(255) NOT NULL
    );
    """)

    # Tabla 'logisticas'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logisticas (
        id SERIAL PRIMARY KEY,
        nombre VARCHAR(100) UNIQUE NOT NULL
    );
    """)

    conn.commit()
    cursor.close()
    conn.close()


# -------------------------------------------------------
# Funciones para CRUD de 'usuarios'
# -------------------------------------------------------

# database.py

def get_user_by_username(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, hashed_password FROM usuarios WHERE username = %s",
        (username,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {"username": row[0], "hashed_password": row[1]}
    return None

def create_user(username, hashed_password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO usuarios (username, hashed_password) VALUES (%s, %s)",
        (username, hashed_password)
    )
    conn.commit()
    cursor.close()
    conn.close()


# -------------------------------------------------------
# Funciones para CRUD de 'pedidos'
# -------------------------------------------------------

def add_order_if_not_exists(oid, detalle):
    """
    Inserta una fila por cada ítem en detalle["items"]. Si (shipment_id, order_id)
    ya existe, no inserta.
    """
    conn = get_connection()
    cursor = conn.cursor()

    for item in detalle["items"]:
        order_id = item["order_id"]
        titulo = item["titulo"]
        cantidad = item["cantidad"]
        shipment_id = item["shipment_id"]
        cliente = detalle["cliente"]

        try:
            cursor.execute(
                """
                INSERT INTO pedidos (
                    order_id, cliente, titulo, cantidad,
                    estado, fecha_armado, fecha_despacho,
                    logistica, shipment_id, tipo_envio, usuario
                ) VALUES (
                    %s, %s, %s, %s,
                    'pendiente', NULL, NULL,
                    NULL, %s, NULL, NULL
                )
                ON CONFLICT (shipment_id, order_id) DO NOTHING;
                """,
                (order_id, cliente, titulo, cantidad, shipment_id)
            )
        except Exception as e:
            logger.error("Error INSERT pedido: %s", e)

    conn.commit()
    cursor.close()
    conn.close()
    return True


# -------------------------------------------------------
# Funciones para CRUD de 'logisticas'
# -------------------------------------------------------

def get_all_logisticas() -> list[str]:
    """
    Devuelve la lista de nombres de logísticas.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM logisticas ORDER BY nombre;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [r[0] for r in rows]


def add_logistica(nombre: str) -> bool:
    """
    Inserta una logística nueva. Devuelve False si ya existe.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO logisticas (nombre) VALUES (%s);",
            (nombre,)
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        cursor.close()
        conn.close()
        return False
    cursor.close()
    conn.close()
    return True


# -------------------------------------------------------
# Funciones para actualizar estados en 'pedidos'
# -------------------------------------------------------

def marcar_envio_armado(id_buscar: str, usuario: str) -> bool:
    """
    Marca como 'armado' todos los pedidos cuyo shipment_id = id_buscar
    y estado = 'pendiente'. Devuelve True si se actualizó al menos una fila.
    """
    conn = get_connection()
    cursor = conn.cursor()
    ahora = datetime.now()

    cursor.execute(
        """
        UPDATE pedidos
        SET
            estado = 'armado',
            fecha_armado = %s,
            usuario = %s
        WHERE shipment_id = %s
          AND estado = 'pendiente';
        """,
        (ahora, usuario, id_buscar)
    )
    filas_afectadas = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return filas_afectadas > 0


def marcar_pedido_despachado(
    id_buscar: str,
    logistica: str,
    tipo_envio: str,
    usuario: str
) -> bool:
    """
    Marca como 'despachado' todos los pedidos cuyo shipment_id = id_buscar
    y estado = 'armado'. Devuelve True si se actualizó al menos una fila.
    """
    conn = get_connection()
    cursor = conn.cursor()
    ahora = datetime.now()

    cursor.execute(
        """
        UPDATE pedidos
        SET
            estado = 'despachado',
            fecha_despacho = %s,
            logistica = %s,
            tipo_envio = %s,
            usuario = %s
        WHERE shipment_id = %s
          AND estado = 'armado';
        """,
        (ahora, logistica, tipo_envio, usuario, id_buscar)
    )
    filas_afectadas = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return filas_afectadas > 0


# -------------------------------------------------------
# Función para listar pedidos con filtros opcionales
# -------------------------------------------------------

def get_all_pedidos(
    order_id: str = None,
    shipment_id: str = None,
    date_from: str = None,
    date_to: str = None,
    logistica: str = None
) -> list[dict]:
    """
    Devuelve lista de dicts con todos los pedidos, opcionalmente filtrados.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query = """
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
        WHERE TRUE
    """
    params = []

    if order_id:
        query += " AND order_id ILIKE %s"
        params.append(f"%{order_id}%")
    if shipment_id:
        query += " AND shipment_id ILIKE %s"
        params.append(f"%{shipment_id}%")
    if date_from:
        query += " AND (fecha_armado >= %s OR fecha_despacho >= %s)"
        params.extend([date_from, date_from])
    if date_to:
        query += " AND (fecha_armado <= %s OR fecha_despacho <= %s)"
        params.extend([date_to, date_to])
    if logistica:
        query += " AND logistica = %s"
        params.append(logistica)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    pedidos = []
    for row in rows:
        pedidos.append({
            "order_id": row[0],
            "cliente": row[1],
            "titulo": row[2],
            "cantidad": row[3],
            "estado": row[4],
            "fecha_armado": row[5].strftime("%Y-%m-%d %H:%M:%S") if row[5] else None,
            "fecha_despacho": row[6].strftime("%Y-%m-%d %H:%M:%S") if row[6] else None,
            "logistica": row[7],
            "shipment_id": row[8],
            "tipo_envio": row[9],
            "usuario": row[10]
        })
    return pedidos
