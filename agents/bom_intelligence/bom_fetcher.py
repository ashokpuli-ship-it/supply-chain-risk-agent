from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import openpyxl

from models import BOMComponent, BOMData, SiliconExpertData

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
    "Country of Origin":        "country_of_origin",
    "Quantity":                 "quantity",
    "Lead Time (Days)":         "lead_time_days",
    "MOQ":                      "moq",
    "Multiple Source Status":   "multiple_source_status",
    "Unique to Samsara":        "unique_to_samsara",
    "Is Substitute":            "is_substitute",
    "Reference Designators":    "reference_designators",
    "Vendor":                   "vendor",
    "Vendor Part#":             "vendor_part",
    "Flag Risk Review":         "flag_risk_review",
}

# SiliconExpert lifecycle column headers (present in Propel + SE integrated exports)
_SE_COLUMNS = {
    "LifecycleStage",
    "EstimatedEOLDate",
    "EstimatedYearsToEOL",
    "MinEstimatedYearsToEOL",
    "MaxEstimatedYearsToEOL",
    "LifeCycleRiskGrade",
    "LastPCNDate",
    "NumberOfDistributors",
    "InventoryRisk",
    "CounterfeitOverallRisk",
    "MultiSourcingRisk",
    "OverallRisk",
}

# Fallback SE defaults when SE columns are absent (derived from Lifecycle Phase)
_SE_FALLBACK: dict[str | None, dict] = {
    "ACTIVE": {
        "lifecycle_stage": "ACTIVE",
        "estimated_years_to_eol": 7.0,
        "number_of_distributors": 10,
        "inventory_risk": "Low",
        "counterfeit_overall_risk": "Low",
    },
    "NRND": {
        "lifecycle_stage": "NRND",
        "estimated_years_to_eol": 3.0,
        "number_of_distributors": 5,
        "inventory_risk": "Medium",
        "counterfeit_overall_risk": "Low",
    },
    "LTB": {
        "lifecycle_stage": "LTB",
        "estimated_years_to_eol": 1.0,
        "number_of_distributors": 3,
        "inventory_risk": "High",
        "counterfeit_overall_risk": "Medium",
    },
    "EOL": {
        "lifecycle_stage": "Obsolete",
        "estimated_years_to_eol": 0.0,
        "number_of_distributors": 1,
        "inventory_risk": "High",
        "counterfeit_overall_risk": "High",
    },
    None: {
        "lifecycle_stage": "ACTIVE",
        "estimated_years_to_eol": 7.0,
        "number_of_distributors": 10,
        "inventory_risk": "Low",
        "counterfeit_overall_risk": "Low",
    },
}


def _parse_bool(value) -> Optional[bool]:
    """Parse Yes/No/True/False/1/0 cell values to bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("yes", "true", "1"):
        return True
    if s in ("no", "false", "0"):
        return False
    return None


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
    try:
        ws = wb.active
        rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    finally:
        wb.close()

    if not rows:
        raise ValueError(f"Empty workbook: {filepath}")

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    idx: dict[str, int] = {col: headers.index(col) for col in _EXCEL_COLUMNS if col in headers}

    # Detect which SE columns are present in this workbook
    se_idx: dict[str, int] = {col: headers.index(col) for col in _SE_COLUMNS if col in headers}
    has_se_columns = bool(se_idx)

    sku: Optional[BOMComponent] = None
    components: list[BOMComponent] = []

    for row in rows[1:]:
        raw_item = _cell(row, idx, "Item Number")
        if raw_item is None:
            continue

        raw_level  = _cell(row, idx, "Level")
        raw_sub_for = _cell(row, idx, "Substitute For")
        raw_crit   = _cell(row, idx, "Criticality Type")
        raw_coo    = _cell(row, idx, "Country of Origin")
        raw_qty    = _cell(row, idx, "Quantity")
        raw_lt     = _cell(row, idx, "Lead Time (Days)")
        raw_moq    = _cell(row, idx, "MOQ")
        raw_mss    = _cell(row, idx, "Multiple Source Status")
        raw_unique = _cell(row, idx, "Unique to Samsara")
        raw_is_sub = _cell(row, idx, "Is Substitute")
        raw_flag   = _cell(row, idx, "Flag Risk Review")

        level = int(raw_level) if raw_level is not None else 0

        lifecycle_phase = _cell(row, idx, "Lifecycle Phase")

        # Build SiliconExpertData — from SE columns if present, else derive from lifecycle_phase
        if has_se_columns:
            def _se(col: str):
                i = se_idx.get(col)
                v = row[i] if i is not None else None
                return str(v).strip() if v not in (None, "None", "") else None

            se_data = SiliconExpertData(
                lifecycle_stage=_se("LifecycleStage"),
                estimated_eol_date=_se("EstimatedEOLDate"),
                estimated_years_to_eol=float(_se("EstimatedYearsToEOL")) if _se("EstimatedYearsToEOL") is not None else None,
                min_years_to_eol=float(_se("MinEstimatedYearsToEOL")) if _se("MinEstimatedYearsToEOL") is not None else None,
                max_years_to_eol=float(_se("MaxEstimatedYearsToEOL")) if _se("MaxEstimatedYearsToEOL") is not None else None,
                lifecycle_risk_grade=_se("LifeCycleRiskGrade"),
                last_pcn_date=_se("LastPCNDate"),
                number_of_distributors=int(float(_se("NumberOfDistributors"))) if _se("NumberOfDistributors") is not None else None,
                inventory_risk=_se("InventoryRisk"),
                counterfeit_overall_risk=_se("CounterfeitOverallRisk"),
                multi_sourcing_risk=_se("MultiSourcingRisk"),
                overall_risk=_se("OverallRisk"),
            )
        else:
            lp_key = str(lifecycle_phase).strip() if lifecycle_phase else None
            defaults = _SE_FALLBACK.get(lp_key, _SE_FALLBACK[None])
            se_data = SiliconExpertData(**defaults)

        component = BOMComponent(
            level=level,
            item_number=str(raw_item),
            substitute_for=str(raw_sub_for) if raw_sub_for is not None else None,
            description=_cell(row, idx, "Description"),
            manufacturer=_cell(row, idx, "Manufacturer"),
            mpn=_cell(row, idx, "Manufacturer Part Number"),
            lifecycle_phase=lifecycle_phase,
            criticality_type=str(raw_crit) if raw_crit not in (None, "None") else None,
            country_of_origin=str(raw_coo).strip() if raw_coo not in (None, "None", "") else None,
            quantity=float(raw_qty) if raw_qty is not None else None,
            lead_time_days=float(raw_lt) if raw_lt is not None else None,
            moq=float(raw_moq) if raw_moq is not None else None,
            multiple_source_status=str(raw_mss).strip() if raw_mss not in (None, "None", "") else None,
            unique_to_samsara=_parse_bool(raw_unique),
            is_substitute=_parse_bool(raw_is_sub) or False,
            reference_designators=_cell(row, idx, "Reference Designators"),
            vendor=_cell(row, idx, "Vendor"),
            vendor_part=_cell(row, idx, "Vendor Part#"),
            flag_risk_review=_parse_bool(raw_flag),
            se_data=se_data,
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
