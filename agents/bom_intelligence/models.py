from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SubstituteRisk(str, Enum):
    HIGH = "HIGH"       # No substitute — single source
    MEDIUM = "MEDIUM"   # Substitute exists but same manufacturer or same region
    LOW = "LOW"         # Substitute exists, different manufacturer AND different region


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
