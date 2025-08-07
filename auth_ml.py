import webbrowser
import requests
import json
from datetime import datetime
import os

# DATOS DE TU APP
CLIENT_ID = "5569606371936049"
CLIENT_SECRET = "wH7UDWXbA92DVlYa4P50cHBCLrEloMa0"
REDIRECT_URI = "https://controlpedidos.onrender.com/callback"
TOKEN_PATH = os.getenv("ML_TOKEN_PATH", "/app/ml_token.json")

# 1. ABRIR URL DE AUTORIZACIÓN
def solicitar_codigo():
    auth_url = f"https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    print("👉 Abrí esta URL en tu navegador y autorizá la aplicación:")
    print(auth_url)
    webbrowser.open(auth_url)

# 2. INTERCAMBIAR CODE POR ACCESS TOKEN Y GUARDARLO
def obtener_token(code):
    token_url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    response = requests.post(token_url, data=payload)
    if response.status_code == 200:
        data = response.json()
        data["created_at"] = datetime.now().isoformat()

        # Asegurarse de que exista la carpeta
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)

        with open(TOKEN_PATH, "w") as f:
            json.dump(data, f, indent=2)

        print("✅ Token guardado en", TOKEN_PATH)
        print("🔑 Access Token:", data["access_token"])
    else:
        print("❌ Error al obtener el token:", response.status_code)
        print(response.json())

# auth_ml.py — reemplazá la función
def get_ml_token():
    with open(TOKEN_PATH, "r") as f:
        data = json.load(f)
    return data["access_token"]

# --- EJECUCIÓN ---
if __name__ == "__main__":
    solicitar_codigo()
    code = input("\n🔁 Pegá aquí el code de la URL: ")
    obtener_token(code)
