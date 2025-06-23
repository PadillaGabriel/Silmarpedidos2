from database.models import ChecklistItem
from api_ml import get_order_details  # importá desde donde esté

def checklist_completo(session, shipment_id: str) -> bool:
    try:
        detalle = get_order_details(shipment_id=shipment_id)
        if not detalle or "items" not in detalle:
            print("❌ Detalle vacío o sin ítems")
            return False

        # 1. Extraer todos los order_ids únicos del shipment
        primer_oid = detalle.get("primer_order_id")
        if not primer_oid:
            print("❌ No se encontró order_id principal")
            return False

        # 2. Contar cuántos ítems hay realmente en el detalle del pedido
        cantidad_total_items = len(detalle["items"])

        # 3. Contar cuántos ítems se marcaron para ese shipment_id
        cantidad_marcados = session.query(ChecklistItem).filter(
            ChecklistItem.shipment_id == shipment_id,
            ChecklistItem.marcado == True
        ).count()

        print(f"📦 Total en pedido: {cantidad_total_items}, Marcados: {cantidad_marcados}")

        return cantidad_marcados >= cantidad_total_items

    except Exception as e:
        print(f"❌ Error en checklist_completo: {e}")
        return False
