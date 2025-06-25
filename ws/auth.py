import requests
import json
import os
from xml.etree import ElementTree as ET

AUTH_FILE = "ws_auth.json"

def cargar_credenciales(path=AUTH_FILE):
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el archivo de credenciales: {path}")
    with open(path, "r") as f:
        return json.load(f)

def guardar_credenciales(datos, path=AUTH_FILE):
    with open(path, "w") as f:
        json.dump(datos, f, indent=2)

def autenticar_desde_json(force_renovar=False, path=AUTH_FILE):
    datos = cargar_credenciales(path)

    # Si ya tiene token y no se pide renovar, devolverlo
    if datos.get("token") and not force_renovar:
        print("🔐 Usando token existente desde archivo.")
        return datos["token"]

    # Autenticación SOAP
    url = "https://ws.globalbluepoint.com/silmarbazar/app_webservices/wsBasicQuery.asmx"
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://microsoft.com/webservices/AuthenticateUser"
    }

    soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>{datos['username']}</pUsername>
          <pPassword>{datos['password']}</pPassword>
          <pCompany>{datos['company_id']}</pCompany>
          <pWebWervice>{datos['webservice_id']}</pWebWervice>
          <pAuthenticatedToken></pAuthenticatedToken>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        <AuthenticateUser xmlns="http://microsoft.com/webservices/" />
      </soap:Body>
    </soap:Envelope>"""

    res = requests.post(url, data=soap_body.encode("utf-8"), headers=headers)

    if res.status_code == 200:
        tree = ET.fromstring(res.content)
        ns = {
            'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
            'm': 'http://microsoft.com/webservices/'
        }
        token = tree.find('.//m:AuthenticateUserResult', ns)
        if token is not None:
            datos["token"] = token.text
            guardar_credenciales(datos, path)
            print("✅ Nuevo token autenticado y guardado.")
            return token.text
        else:
            print("❌ No se encontró el token en la respuesta.")
            return None
    else:
        print(f"❌ Error HTTP {res.status_code}:")
        print(res.text)
        return None
