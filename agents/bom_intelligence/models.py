from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


# Lifecycle phases that carry elevated risk — shared across modules
AT_RISK_LIFECYCLE: set[str] = {"EOL", "LTB", "NRND"}

# Criticality types that amplify component risk severity
CRITICAL_TYPES: set[str] = {"Field", "Safety", "Field & Safety"}


class SubstituteRisk(str, Enum):
    HIGH = "HIGH"       # No substitute — single source
    MEDIUM = "MEDIUM"   # Substitute exists but same manufacturer or same region
    LOW = "LOW"         # Substitute exists, different manufacturer AND different region


class SiliconExpertData(BaseModel):
    """SiliconExpert lifecycle intelligence fields per component."""
    lifecycle_stage: Optional[str] = None           # ACTIVE | NRND | LTB | Obsolete
    estimated_eol_date: Optional[str] = None        # "YYYY-MM-DD"
    estimated_years_to_eol: Optional[float] = None
    min_years_to_eol: Optional[float] = None
    max_years_to_eol: Optional[float] = None
    lifecycle_risk_grade: Optional[str] = None      # A | B | C | D | F
    last_pcn_date: Optional[str] = None             # "YYYY-MM-DD"
    number_of_distributors: Optional[int] = None
    inventory_risk: Optional[str] = None            # Low | Medium | High
    counterfeit_overall_risk: Optional[str] = None  # Low | Medium | High
    multi_sourcing_risk: Optional[str] = None       # Low | Medium | High
    overall_risk: Optional[str] = None              # Low | Medium | High


class BOMComponent(BaseModel):
    level: int
    item_number: str
    substitute_for: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    mpn: Optional[str] = None
    lifecycle_phase: Optional[str] = None
    criticality_type: Optional[str] = None          # Function | Field | Safety | Field & Safety | NA
    country_of_origin: Optional[str] = None         # Country where component is manufactured
    quantity: Optional[float] = None
    lead_time_days: Optional[float] = None
    moq: Optional[float] = None                     # Minimum Order Quantity
    multiple_source_status: Optional[str] = None    # Single | Multi
    unique_to_samsara: Optional[bool] = None        # Yes = limited ecosystem alternatives
    is_substitute: bool = False
    reference_designators: Optional[str] = None
    vendor: Optional[str] = None
    vendor_part: Optional[str] = None
    flag_risk_review: Optional[bool] = None
    # SiliconExpert lifecycle fields (populated by bom_fetcher when SE columns present)
    se_data: Optional[SiliconExpertData] = None


class BOMData(BaseModel):
    sku_id: str
    description: str
    components: list[BOMComponent]

    @property
    def primary_components(self) -> list[BOMComponent]:
        return [c for c in self.components if not c.is_substitute]

    @property
    def substitute_components(self) -> list[BOMComponent]:
        return [c for c in self.components if c.is_substitute]


class SubstituteInfo(BaseModel):
    item_number: str
    manufacturer: Optional[str] = None
    mpn: Optional[str] = None
    lifecycle_phase: Optional[str] = None
    country_of_origin: Optional[str] = None


class ComponentRisk(BaseModel):
    item_number: str
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    mpn: Optional[str] = None
    lifecycle_phase: Optional[str] = None
    criticality_type: Optional[str] = None
    country_of_origin: Optional[str] = None
    lead_time_days: Optional[float] = None
    moq: Optional[float] = None
    multiple_source_status: Optional[str] = None
    unique_to_samsara: Optional[bool] = None
    substitute_risk: SubstituteRisk
    substitutes: list[SubstituteInfo] = []
    risk_score: float
    risk_drivers: list[str] = []


class SKURiskReport(BaseModel):
    sku_id: str
    description: str
    total_components: int
    single_source_count: int
    components_with_substitutes: int
    weak_substitute_count: int          # Substitutes sharing same manufacturer or region
    at_risk_lifecycle_count: int        # EOL + LTB + NRND components
    critical_parts_count: int           # Field / Safety / Field & Safety components
    unique_to_samsara_count: int        # Components unique to Samsara ecosystem
    risk_score: float
    risk_level: str                     # LOW | MEDIUM | HIGH | CRITICAL
    component_risks: list[ComponentRisk]
    top_risks: list[str]


# ── Lifecycle & Obsolescence Agent output models ──────────────────────────────

class LifecycleComponentRisk(BaseModel):
    """Per-component lifecycle risk score from the Lifecycle & Obsolescence Agent."""
    item_number: str
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    mpn: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    estimated_years_to_eol: Optional[float] = None
    estimated_eol_date: Optional[str] = None
    number_of_distributors: Optional[int] = None
    counterfeit_risk: Optional[str] = None
    lifecycle_risk_score: float                     # 0–100
    lifecycle_risk_level: str                       # LOW | MEDIUM | HIGH | CRITICAL
    risk_drivers: list[str] = []


class LifecycleRiskReport(BaseModel):
    """SKU-level lifecycle risk summary."""
    sku_id: str
    description: str
    total_components: int
    obsolete_count: int                 # Lifecycle stage = Obsolete/EOL
    nrnd_count: int                     # Lifecycle stage = NRND
    ltb_count: int                      # Lifecycle stage = LTB
    near_eol_count: int                 # estimated_years_to_eol < 2
    low_distributor_count: int          # number_of_distributors < 2
    high_counterfeit_count: int         # counterfeit_overall_risk = High
    lifecycle_risk_score: float         # 0–100 (SKU-level weighted)
    lifecycle_risk_level: str           # LOW | MEDIUM | HIGH | CRITICAL
    component_risks: list[LifecycleComponentRisk]
    top_lifecycle_risks: list[str]      # Narrative (e.g. "1 component is Obsolete")


# ── Orchestrator output model ─────────────────────────────────────────────────

class CompositeRiskReport(BaseModel):
    """
    Composite risk report from the Risk Orchestrator.

    Phase 1 formula (2 of 3 agents active):
        composite = 0.5625 × structural + 0.4375 × lifecycle
    Weights normalised from spec (0.45 structural, 0.35 lifecycle, 0.20 supply).
    Supply Agent weight (0.20) reintroduced once that agent is built.
    """
    sku_id: str
    description: str
    structural_risk_score: float        # From SKURiskReport
    structural_risk_level: str
    lifecycle_risk_score: float         # From LifecycleRiskReport
    lifecycle_risk_level: str
    composite_risk_score: float         # Weighted aggregate (0–100)
    composite_risk_level: str           # LOW | MEDIUM | HIGH | CRITICAL
    active_agents: list[str]            # e.g. ["bom_intelligence", "lifecycle"]
    correlation_signals: list[str]      # Compound risk detections
    top_risks: list[str]                # Merged executive narrative
