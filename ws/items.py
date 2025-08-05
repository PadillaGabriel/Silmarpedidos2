import requests
import xml.etree.ElementTree as ET
from ws.auth import autenticar_desde_json

WSDL_URL = "https://ws.globalbluepoint.com/silmarbazar/app_webservices/wsBasicQuery.asmx"
HEADERS_SOAP = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": "http://microsoft.com/webservices/Item_funGetXMLData"
}

def obtener_todos_los_items(token: str) -> str:
    body = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema" 
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>ustrebolnet</pUsername>
          <pPassword>1234</pPassword>
          <pCompany>1</pCompany>
          <pWebWervice>1000</pWebWervice>
          <pAuthenticatedToken>{token}</pAuthenticatedToken>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        <Item_funGetXMLData xmlns="http://microsoft.com/webservices/" />
      </soap:Body>
    </soap:Envelope>"""

    result = requests.post(WSDL_URL, data=body.encode("utf-8"), headers=HEADERS_SOAP)

    print("📨 XML crudo recibido:")
    print(result.text[:1000])  # Primeros 1000 caracteres

    try:
        tree = ET.fromstring(result.text)
        nodo = tree.find(".//{http://microsoft.com/webservices/}Item_funGetXMLDataResult")
        if nodo is None or not nodo.text:
            print("❌ Nodo vacío o no encontrado")
            return ""
        
        if "TOKEN Expired" in nodo.text:
            print("🔁 Token expirado detectado, reautenticando...")
            
            new_token = autenticar_desde_json(force_renovar=True)
            return obtener_todos_los_items(new_token)

        return nodo.text
    except ET.ParseError as e:
        print("❌ Error parseando el XML:", e)
        return ""    
    

def parsear_items(xml_texto: str) -> list[dict]:
    items_extraidos = []
    root = ET.fromstring(xml_texto)
    for item in root.findall("Table"):
        items_extraidos.append({
            "item_id": item.findtext("item_id"),
            "item_code": item.findtext("item_code"),
            "item_vendorCode": item.findtext("item_vendorCode")
        })
    return items_extraidos

def buscar_item_por_sku(sku: str):
    token = autenticar_desde_json()
    datos = obtener_todos_los_items(token)
    items = parsear_items(datos)
    for item in items:
        if item["item_code"] == sku:
            print(f"🎯 Coincidencia para SKU {sku}: {item}")
            return item
    return None
