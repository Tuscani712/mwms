"""Receiving business logic — ASN → check-in → receipt → putaway."""

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from wms.models import ASN, SKU, ASNLine, Location, Lot, Receipt, ReceiptLine
from wms.schemas.receiving import PutawaySuggestion, ReceiptCreate


def list_inbound(db: Session, site_id: str) -> list[ASN]:
    return (
        db.query(ASN)
        .filter(ASN.site_id == site_id, ASN.status.in_(["scheduled", "arrived", "receiving"]))
        .order_by(ASN.eta.asc().nullslast())
        .all()
    )


def check_in_asn(db: Session, site_id: str, asn_id: int, dock_door: str) -> ASN:
    asn = db.query(ASN).filter(ASN.id == asn_id, ASN.site_id == site_id).one()
    if asn.status not in {"scheduled", "arrived"}:
        raise ValueError(f"ASN cannot check in from status '{asn.status}'")
    asn.dock_door = dock_door
    asn.status = "receiving"
    asn.arrived_at = datetime.now(UTC)
    db.commit()
    db.refresh(asn)
    return asn


def create_receipt(
    db: Session, site_id: str, user_id: int | None, payload: ReceiptCreate
) -> Receipt:
    asn = db.query(ASN).filter(ASN.id == payload.asn_id, ASN.site_id == site_id).one()
    if asn.status != "receiving":
        raise ValueError(f"ASN must be in receiving status (currently '{asn.status}')")

    receipt = Receipt(
        site_id=site_id,
        asn_id=asn.id,
        received_by=user_id,
        variance_notes=payload.variance_notes,
    )
    db.add(receipt)
    db.flush()

    total_variance = 0
    for line_in in payload.lines:
        asn_line = (
            db.query(ASNLine).filter(ASNLine.id == line_in.asn_line_id, ASNLine.asn_id == asn.id).one()
        )
        sku = db.query(SKU).filter(SKU.id == asn_line.sku_id).one()
        variance = line_in.qty_received - asn_line.expected_qty
        total_variance += variance

        # Create a Lot for the received goods (or to QA-hold if QC failed)
        lot = Lot(
            site_id=site_id,
            lot_code=f"LOT-{asn.asn_code}-{asn_line.id}",
            sku_id=sku.id,
            quantity=line_in.qty_received,
            qa_hold=not line_in.qc_passed,
            supplier=asn.supplier,
        )
        db.add(lot)
        db.flush()

        rline = ReceiptLine(
            receipt_id=receipt.id,
            asn_line_id=asn_line.id,
            lot_id=lot.id,
            qty_received=line_in.qty_received,
            qty_variance=variance,
            qc_passed=line_in.qc_passed,
        )
        db.add(rline)

        asn_line.received_qty = line_in.qty_received
        asn_line.qc_status = "passed" if line_in.qc_passed else "hold"

    asn.status = "received"
    asn.received_at = datetime.now(UTC)
    db.commit()
    db.refresh(receipt)
    return receipt


def putaway_suggestions(
    db: Session, site_id: str, asn_id: int
) -> list[PutawaySuggestion]:
    """Suggest primary FIFO + overflow location for each line of an ASN."""
    asn = db.query(ASN).filter(ASN.id == asn_id, ASN.site_id == site_id).one()

    suggestions: list[PutawaySuggestion] = []
    for line in asn.lines:
        sku = db.query(SKU).filter(SKU.id == line.sku_id).one()
        used_per_location = dict(
            db.query(Lot.location_id, func.sum(Lot.quantity))
            .filter(Lot.site_id == site_id, Lot.location_id.isnot(None))
            .group_by(Lot.location_id)
            .all()
        )

        primary = (
            db.query(Location)
            .filter(
                Location.site_id == site_id,
                Location.is_overflow.is_(False),
                Location.is_qa_hold.is_(False),
            )
            .order_by(Location.code)
            .first()
        )
        overflow = (
            db.query(Location)
            .filter(Location.site_id == site_id, Location.is_overflow.is_(True))
            .order_by(Location.code)
            .first()
        )

        def cap_left(loc: Location | None, used_map: dict = used_per_location) -> int:
            if loc is None:
                return 0
            used = used_map.get(loc.id, 0) or 0
            return max(0, loc.capacity - int(used))

        primary_cap = cap_left(primary)
        overflow_cap = cap_left(overflow)
        qty = line.expected_qty
        rationale = (
            "FIFO primary fits full quantity"
            if primary_cap >= qty
            else "Primary near capacity — overflow recommended for excess"
        )

        suggestions.append(
            PutawaySuggestion(
                sku_code=sku.code,
                qty=qty,
                primary_location=primary.code if primary else None,
                primary_capacity_left=primary_cap,
                overflow_location=overflow.code if overflow else None,
                overflow_capacity_left=overflow_cap,
                rationale=rationale,
            )
        )
    return suggestions
