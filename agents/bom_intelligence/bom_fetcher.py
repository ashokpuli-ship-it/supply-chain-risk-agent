from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import openpyxl

from models import BOMComponent, BOMData

# Maps Excel column headers to BOMComponent field names
_EXCEL_COLUMNS = {
    "Level":                    "level",
    "Item Number":              "item_number",
    "Substitute For":           "substitute_for",
    "Description":              "description",
    "Manufacturer":             "manufacturer",
    "Manufacturer Part Number": "mpn",
    "Lifecycle Phase":          "lifecycle_phase",
    "Criticality Type":         "criticality_type",
    "Quantity":                 "quantity",
    "Lead Time (Days)":         "lead_time_days",
    "Is Substitute":            "is_substitute",
    "Reference Designators":    "reference_designators",
    "Vendor":                   "vendor",
    "Vendor Part#":             "vendor_part",
    "Flag Risk Review":         "flag_risk_review",
}


def _cell(row: tuple, idx: dict[str, int], key: str):
    """Safely retrieve a cell value by column name. Returns None if column missing."""
    i = idx.get(key)
    return row[i] if i is not None else None


def fetch_from_excel(filepath: str | Path) -> BOMData:
    """
    Load a BOM from a Propel PLM Excel export.

    The file structure matches the Propel BOM export format:
    - Row 0: column headers
    - Subsequent rows: BOM items (Level 0 = SKU, Level 1+ = components)
    - Substitute rows have Is Substitute = True and Substitute For = <primary item number>
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]

    if not rows:
        raise ValueError(f"Empty workbook: {filepath}")

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    idx: dict[str, int] = {col: headers.index(col) for col in _EXCEL_COLUMNS if col in headers}

    sku: Optional[BOMComponent] = None
    components: list[BOMComponent] = []

    for row in rows[1:]:
        raw_item = _cell(row, idx, "Item Number")
        if raw_item is None:
            continue

        raw_level = _cell(row, idx, "Level")
        raw_sub_for = _cell(row, idx, "Substitute For")
        raw_crit = _cell(row, idx, "Criticality Type")
        raw_qty = _cell(row, idx, "Quantity")
        raw_lt = _cell(row, idx, "Lead Time (Days)")
        raw_is_sub = _cell(row, idx, "Is Substitute")
        raw_flag = _cell(row, idx, "Flag Risk Review")

        level = int(raw_level) if raw_level is not None else 0

        component = BOMComponent(
            level=level,
            item_number=str(raw_item),
            substitute_for=str(raw_sub_for) if raw_sub_for is not None else None,
            description=_cell(row, idx, "Description"),
            manufacturer=_cell(row, idx, "Manufacturer"),
            mpn=_cell(row, idx, "Manufacturer Part Number"),
            lifecycle_phase=_cell(row, idx, "Lifecycle Phase"),
            criticality_type=str(raw_crit) if raw_crit not in (None, "None") else None,
            quantity=float(raw_qty) if raw_qty is not None else None,
            lead_time_days=float(raw_lt) if raw_lt is not None else None,
            is_substitute=bool(raw_is_sub) if raw_is_sub is not None else False,
            reference_designators=_cell(row, idx, "Reference Designators"),
            vendor=_cell(row, idx, "Vendor"),
            vendor_part=_cell(row, idx, "Vendor Part#"),
            flag_risk_review=bool(raw_flag) if raw_flag is not None else None,
        )

        if level == 0:
            sku = component
        else:
            components.append(component)

    if sku is None:
        raise ValueError("No Level-0 SKU row found in BOM file.")

    return BOMData(
        sku_id=sku.item_number,
        description=sku.description or "",
        components=components,
    )


# ── Propel REST API Placeholder ───────────────────────────────────────────────

class PropelAPIClient:
    """
    Placeholder for the Propel PLM REST API integration.

    Auth:    OAuth2 client_credentials grant
    Docs:    https://developer.propelsoftware.com
    Env:     PROPEL_BASE_URL, PROPEL_CLIENT_ID, PROPEL_CLIENT_SECRET

    The Propel BOM API response is expected to map to the same column schema
    as the Excel export. Implement fetch_bom() once API credentials are available.
    """

    def __init__(self, base_url: str, access_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    @classmethod
    async def authenticate(
        cls, base_url: str, client_id: str, client_secret: str
    ) -> "PropelAPIClient":
        """
        Exchange client credentials for an OAuth2 access token.
        TODO: implement when Propel credentials are available.
        """
        raise NotImplementedError(
            "Propel OAuth2 not yet implemented. "
            "Set PROPEL_BASE_URL, PROPEL_CLIENT_ID, PROPEL_CLIENT_SECRET in .env"
        )

    async def fetch_bom(self, sku_id: str) -> BOMData:
        """
        GET /v1/items/{sku_id}/bom  (expected Propel endpoint — confirm in API docs)

        Response JSON should include fields matching the Excel export column schema.
        Map the response keys to BOMComponent fields using _EXCEL_COLUMNS as reference.
        TODO: implement response mapping once endpoint is confirmed.
        """
        raise NotImplementedError(
            "Propel BOM API not yet integrated. Use fetch_from_excel() for POC."
        )
