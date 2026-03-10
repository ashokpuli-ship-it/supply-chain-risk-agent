from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from bom_fetcher import fetch_from_excel
from bom_graph_builder import build_graph, get_where_used
from database import DBComponent, DBRiskScore, get_session, init_db
from models import BOMData, SKURiskReport
from risk_engine import compute_risk_report

load_dotenv()

_HERE = Path(__file__).parent
_STATIC_DIR = _HERE / "static"
_SAMPLE_BOM = _HERE.parent.parent / "Project Docs" / "Sample BOM.xlsx"

_bom_cache: dict[str, BOMData] = {}
_report_cache: dict[str, SKURiskReport] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if _SAMPLE_BOM.exists():
        _load_and_cache(str(_SAMPLE_BOM))
        print(f"[startup] Loaded sample BOM: {_SAMPLE_BOM.name}")
    else:
        print(f"[startup] Sample BOM not found at {_SAMPLE_BOM}. POST /bom/load to load data.")
    yield


app = FastAPI(
    title="BOM Intelligence Agent",
    description="Supply Chain Risk Intelligence - BOM Analysis Engine (POC)",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))


def _load_and_cache(filepath: str) -> SKURiskReport:
    bom = fetch_from_excel(filepath)
    G = build_graph(bom)
    report = compute_risk_report(bom, G)
    _bom_cache[bom.sku_id] = bom
    _report_cache[bom.sku_id] = report
    _persist_to_db(bom, report)
    return report


def _persist_to_db(bom: BOMData, report: SKURiskReport) -> None:
    with get_session() as session:
        if session is None:
            return
        session.query(DBComponent).filter(DBComponent.sku_id == bom.sku_id).delete()
        for comp in bom.components:
            session.add(DBComponent(
                sku_id=bom.sku_id,
                item_number=comp.item_number,
                substitute_for=comp.substitute_for,
                description=comp.description,
                manufacturer=comp.manufacturer,
                mpn=comp.mpn,
                lifecycle_phase=comp.lifecycle_phase,
                criticality_type=comp.criticality_type,
                country_of_origin=comp.country_of_origin,
                quantity=comp.quantity,
                lead_time_days=comp.lead_time_days,
                moq=comp.moq,
                multiple_source_status=comp.multiple_source_status,
                unique_to_samsara=comp.unique_to_samsara,
                is_substitute=comp.is_substitute,
                vendor=comp.vendor,
                vendor_part=comp.vendor_part,
                flag_risk_review=comp.flag_risk_review,
            ))
        session.add(DBRiskScore(
            sku_id=report.sku_id,
            sku_description=report.description,
            total_components=report.total_components,
            single_source_count=report.single_source_count,
            components_with_substitutes=report.components_with_substitutes,
            weak_substitute_count=report.weak_substitute_count,
            at_risk_lifecycle_count=report.at_risk_lifecycle_count,
            critical_parts_count=report.critical_parts_count,
            unique_to_samsara_count=report.unique_to_samsara_count,
            risk_score=report.risk_score,
            risk_level=report.risk_level,
            top_risks=report.top_risks,
            component_risks=[c.model_dump() for c in report.component_risks],
        ))


@app.post("/bom/load", response_model=SKURiskReport,
          summary="Load a BOM from an Excel file and run risk analysis")
async def load_bom(
    filepath: str = Query(
        default=str(_SAMPLE_BOM),
        description="Absolute path to a Propel-exported BOM Excel file",
    )
):
    if not Path(filepath).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    try:
        return _load_and_cache(filepath)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/risk/skus", summary="List all loaded SKUs with summary risk scores")
async def list_skus():
    return [
        {
            "sku_id": r.sku_id,
            "description": r.description,
            "risk_score": r.risk_score,
            "risk_level": r.risk_level,
            "total_components": r.total_components,
            "single_source_count": r.single_source_count,
            "components_with_substitutes": r.components_with_substitutes,
        }
        for r in _report_cache.values()
    ]


@app.get("/risk/sku/{sku_id}", response_model=SKURiskReport,
         summary="Full risk report for a SKU")
async def get_sku_risk(sku_id: str):
    report = _report_cache.get(sku_id)
    if not report:
        raise HTTPException(status_code=404,
                            detail=f"SKU '{sku_id}' not loaded. POST /bom/load first.")
    return report


@app.get("/risk/components/high",
         summary="HIGH-risk components across loaded SKUs, sorted by risk score")
async def get_high_risk_components(
    sku_id: Optional[str] = Query(default=None, description="Filter by SKU"),
    limit: int = Query(default=50, ge=1, le=500),
):
    if sku_id:
        if sku_id not in _report_cache:
            raise HTTPException(status_code=404, detail=f"SKU '{sku_id}' not found")
        reports = [_report_cache[sku_id]]
    else:
        reports = list(_report_cache.values())

    high_risk = []
    for report in reports:
        for comp in report.component_risks:
            if comp.substitute_risk == "HIGH":
                high_risk.append({
                    "sku_id": report.sku_id,
                    "item_number": comp.item_number,
                    "description": comp.description,
                    "manufacturer": comp.manufacturer,
                    "mpn": comp.mpn,
                    "lifecycle_phase": comp.lifecycle_phase,
                    "criticality_type": comp.criticality_type,
                    "risk_score": comp.risk_score,
                    "risk_drivers": comp.risk_drivers,
                })

    high_risk.sort(key=lambda x: x["risk_score"], reverse=True)
    return high_risk[:limit]


@app.get("/component/{item_id}/where-used",
         summary="Which SKUs use this component (where-used analysis)")
async def where_used(item_id: str):
    results = []
    for sku_id, bom in _bom_cache.items():
        item_in_bom = any(c.item_number == item_id for c in bom.components)
        if not item_in_bom:
            continue
        G = build_graph(bom)
        used_by = get_where_used(G, item_id)
        results.append({
            "sku_id": sku_id,
            "sku_description": bom.description,
            "used_by_nodes": used_by,
        })
    if not results:
        raise HTTPException(status_code=404,
                            detail=f"Item '{item_id}' not found in any loaded BOM.")
    return results


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "loaded_skus": list(_report_cache.keys())}
