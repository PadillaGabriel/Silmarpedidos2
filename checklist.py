
from database.models import ChecklistItem
from api_ml import get_order_details  # importá desde donde esté


def checklist_completo(session, shipment_id: str) -> bool:
    from database.models import ChecklistItem
    detalle = get_order_details(shipment_id=shipment_id)
    if not detalle or "items" not in detalle:
        return False

    # Solo contar item_id únicos
    item_ids_unicos = {item["item_id"] for item in detalle["items"]}
    marcados = session.query(ChecklistItem).filter_by(
        shipment_id=shipment_id,
        marcado=True
    ).with_entities(ChecklistItem.item_id).distinct().all()

    marcados_set = {item_id for (item_id,) in marcados}

    print(f"✅ Ítems únicos requeridos: {len(item_ids_unicos)} | Ítems marcados: {len(marcados_set)}")

    return item_ids_unicos.issubset(marcados_set)
