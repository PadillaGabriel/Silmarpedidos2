# auth_ml.py
import os, json, time, webbrowser, requests
from datetime import datetime
from pathlib import Path

# ===== CREDENCIALES (podés dejarlas acá o pasarlas por env) =====
CLIENT_ID = os.getenv("ML_CLIENT_ID", "5569606371936049")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "wH7UDWXbA92DVlYa4P50cHBCLrEloMa0")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://controlpedidos.onrender.com/callback")

# Ruta del token (por env) con fallback a la carpeta del proyecto
ROOT = Path(os.getenv("ML_ROOT", Path(__file__).resolve()).parent)
TOKEN_PATH = Path(os.getenv("ML_TOKEN_PATH", ROOT / "ml_token.json"))

# ---------- Paso 1: pedir CODE ----------
def solicitar_codigo():
    auth_url = (
        "https://auth.mercadolibre.com.ar/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    print("👉 Abrí esta URL y autorizá la app:")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    return auth_url  # útil por si lo querés mostrar en UI

# ---------- Paso 2: code → access_token ----------
def obtener_token(code: str):
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    r = requests.post(url, data=payload, timeout=20)
    if r.status_code != 200:
        print("❌ Error al obtener el token:", r.status_code, r.text)
        return None

    data = r.json()
    now = int(time.time())
    data["created_at"] = now
    # ML devuelve expires_in (segundos). Guardamos expires_at para refrescar a tiempo.
    data["expires_at"] = now + int(data.get("expires_in", 0))

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("✅ Token guardado en", TOKEN_PATH)
    print("🔑 Access Token:", data["access_token"])
    return data

# ---------- Refresh ----------
def _refrescar_token(refresh_token: str):
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    now = int(time.time())
    data["created_at"] = now
    data["expires_at"] = now + int(data.get("expires_in", 0))
    # Mantener último refresh_token si ML no lo devuelve
    if "refresh_token" not in data:
        data["refresh_token"] = refresh_token
    TOKEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def _cargar_token():
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"Token file not found: {TOKEN_PATH}")
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))

def get_ml_token() -> str:
    """
    Usala en todas tus llamadas a la API.
    Auto-refresca si faltan <120s para el vencimiento.
    """
    data = _cargar_token()
    # Si no tenemos expires_at (tokens viejos), lo calculamos
    if "expires_at" not in data and "created_at" in data and "expires_in" in data:
        data["expires_at"] = int(data["created_at"]) + int(data["expires_in"])
    # Refresh si está cerca de expirar
    if int(time.time()) >= int(data.get("expires_at", 0)) - 120:
        data = _refrescar_token(data["refresh_token"])
    return data["access_token"]

# ---------- Uso manual ----------
if __name__ == "__main__":
    solicitar_codigo()
    code = input("\n🔁 Pegá aquí el 'code' de la URL: ").strip()
    obtener_token(code)
