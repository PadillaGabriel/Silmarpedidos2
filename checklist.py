
from database.models import ChecklistItem
from api_ml import get_order_details  # importá desde donde esté


def checklist_completo(session, shipment_id: str) -> bool:
    try:
        from database.models import ChecklistItem
        detalle = get_order_details(shipment_id=shipment_id)
        if not detalle or "items" not in detalle:
            print("❌ Detalle vacío o sin ítems")
            return False

        # Contar cuántos item_id distintos hay
        item_ids = {item.get("item_id") for item in detalle["items"] if item.get("item_id")}
        cantidad_total = len(item_ids)

        # Contar marcados en DB por item_id
        cantidad_marcados = session.query(ChecklistItem).filter_by(
            shipment_id=shipment_id,
            marcado=True
        ).distinct(ChecklistItem.item_id).count()

        print(f"✅ Ítems únicos requeridos: {cantidad_total} | Ítems marcados: {cantidad_marcados}")

        return cantidad_marcados >= cantidad_total

    except Exception as e:
        print(f"❌ Error en checklist_completo: {e}")
        return False
