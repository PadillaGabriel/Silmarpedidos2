import requests
import json
from datetime import datetime

CLIENT_ID = "5569606371936049"
CLIENT_SECRET = "wH7UDWXbA92DVIYa4P50cHBCLrEloMa0"
AUTH_CODE = "TG-6802bd5cc2ee3500019b6129-26182591"
REDIRECT_URI = "https://localhost"
TOKEN_PATH = "app/ml_token.json"

payload = {
    "grant_type": "authorization_code",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": AUTH_CODE,
    "redirect_uri": REDIRECT_URI
}

response = requests.post("https://api.mercadolibre.com/oauth/token", data=payload)

if response.status_code == 200:
    token_data = response.json()
    token_data["created_at"] = datetime.now().isoformat()

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print("✅ Token guardado correctamente en", TOKEN_PATH)
else:
    print("❌ Error al obtener el token:")
    print(response.status_code, response.text)
