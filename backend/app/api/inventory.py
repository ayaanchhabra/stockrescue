"""Inventory CSV preview/import and slow-moving dashboard API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Product
from app.services.inventory_csv import (
    MAX_UPLOAD_BYTES,
    InventoryCSVRow,
    InventoryFileError,
    InventoryIssue,
    preview_inventory_csv,
)
from app.services.inventory_import import (
    DEFAULT_RETAILER_ID,
    import_inventory_csv,
)
from app.services.inventory_metrics import build_inventory_dashboard

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _file_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_inventory_file",
            "message": message,
        },
    )


def _read_csv_upload(file: UploadFile) -> bytes:
    """Check the filename and read at most the configured limit plus one byte."""
    filename = (file.filename or "").strip()

    if not filename or Path(filename).suffix.lower() != ".csv":
        raise InventoryFileError(
            "Unsupported file type. Upload a file with a .csv extension."
        )

    # Reading one extra byte lets the validator detect oversized uploads
    # without loading an arbitrarily large file into memory.
    return file.file.read(MAX_UPLOAD_BYTES + 1)


def _issue_out(issue: InventoryIssue) -> dict[str, Any]:
    return {
        "row_number": issue.row_number,
        "field": issue.field,
        "value": issue.value,
        "message": issue.message,
        "severity": issue.severity,
    }


def _row_out(
    row: InventoryCSVRow,
    action: str,
) -> dict[str, Any]:
    return {
        "row_number": row.row_number,
        "product_id": row.product_id,
        "action": action,
        "values": row.values,
        "errors": [_issue_out(issue) for issue in row.errors],
        "warnings": [_issue_out(issue) for issue in row.warnings],
    }


@router.post("/preview")
def preview_inventory(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Validate a CSV and label rows without writing to the database."""
    try:
        content = _read_csv_upload(file)
        preview = preview_inventory_csv(content)
    except InventoryFileError as exc:
        return _file_error(str(exc))

    valid_skus = {
        row.product_id
        for row in preview.valid_rows
        if row.product_id is not None
    }

    existing_skus: set[str] = set()
    if valid_skus:
        statement = select(Product.sku).where(
            Product.retailer_id == DEFAULT_RETAILER_ID,
            Product.sku.in_(valid_skus),
        )
        existing_skus = set(db.scalars(statement).all())

    output_rows = []
    for row in preview.rows:
        if not row.is_valid:
            action = "invalid"
        elif row.product_id in existing_skus:
            action = "will_update"
        else:
            action = "new"

        output_rows.append(_row_out(row, action))

    new_count = sum(r["action"] == "new" for r in output_rows)
    update_count = sum(r["action"] == "will_update" for r in output_rows)
    invalid_count = sum(r["action"] == "invalid" for r in output_rows)
    warning_count = sum(len(r["warnings"]) for r in output_rows)

    return {
        "filename": file.filename,
        "total_rows": len(output_rows),
        "new_count": new_count,
        "update_count": update_count,
        "invalid_count": invalid_count,
        "warning_count": warning_count,
        "rows": output_rows,
    }


@router.post("/import")
def import_inventory(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import valid rows in one transaction and report row-level outcomes."""
    try:
        content = _read_csv_upload(file)
        result = import_inventory_csv(db, content)
    except InventoryFileError as exc:
        return _file_error(str(exc))

    return {
        "created_count": result.created_count,
        "updated_count": result.updated_count,
        "skipped_count": result.skipped_count,
        "imported_count": result.imported_count,
        "rows": [
            {
                "row_number": row.row_number,
                "product_id": row.product_id,
                "action": row.action,
                "errors": row.errors,
                "warnings": row.warnings,
            }
            for row in result.rows
        ],
    }


@router.get("/dashboard")
def inventory_dashboard(db: Session = Depends(get_db)):
    """Return slow-moving metrics for the MVP retailer's current inventory."""
    statement = (
        select(Product)
        .where(Product.retailer_id == DEFAULT_RETAILER_ID)
        .order_by(Product.id)
    )
    products = db.scalars(statement).all()
    dashboard = build_inventory_dashboard(products)

    # Convert dataclasses and tuples into JSON-compatible structures.
    return jsonable_encoder(dashboard)


__all__ = ["router"]
