"""Helpers for Person 2 tests: insert illustrative rows (NOT real Qloo data)."""


def add_product(db, sku, name, qty=10, cost=200.0, price=400.0, **extra) -> int:
    """Insert one illustrative Product row and return its integer pk."""
    from app.models import Product

    p = Product(sku=sku, product_name=name, quantity_in_stock=qty, unit_cost=cost,
                selling_price=price, **extra)
    db.add(p)
    db.commit()
    return p.id


def add_mapping(db, product_pk, status="strong", entity_id="ent-target", verification="unverified",
                matched_name=None, candidates=(), evidence_id=None):
    """Insert an illustrative QlooEntityMapping row."""
    from app.models import QlooEntityMapping

    m = QlooEntityMapping(product_pk=product_pk, qloo_entity_id=entity_id, matched_name=matched_name,
                          match_status=status, match_reason=f"illustrative {status} match",
                          verification_status=verification, candidates=list(candidates),
                          evidence_id=evidence_id)
    db.add(m)
    db.commit()
    return m
