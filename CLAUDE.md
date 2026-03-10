# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Multi-Agent Supply Chain Risk Intelligence Platform** — an AI platform that integrates Propel PLM BOM data with real-time external signals (news, suppliers, logistics, compliance) to provide proactive risk detection and mitigation recommendations.

Phase 1 (POC) of the BOM Intelligence Agent is built and running. The `Project Docs/` folder contains the business case, requirements document, and sample BOM Excel files.

## Development Commands

All commands run from `agents/bom_intelligence/`.

**Setup**
```bash
cd agents/bom_intelligence
# Python 3.12 required (system Python 3.9 is too old for networkx>=3.4)
/usr/local/munki/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL if using PostgreSQL
```

**Run FastAPI server** (JSON API + static dashboard at `http://localhost:8000`)
```bash
cd agents/bom_intelligence
.venv/bin/uvicorn api:app --reload --port 8000
# Interactive API docs: http://localhost:8000/docs
```

**Run Streamlit dashboard** (visual BOM risk UI at `http://localhost:8501`)
```bash
cd agents/bom_intelligence
.venv/bin/streamlit run streamlit_app.py
```

On startup, both interfaces auto-load `Project Docs/Sample BOM.xlsx` if present. PostgreSQL is optional — the app runs in memory-only mode without it.

**Load a BOM via API**
```bash
curl -X POST "http://localhost:8000/bom/load?filepath=/abs/path/to/BOM.xlsx"
```

**If port 8000 is in use:**
```bash
lsof -ti :8000 | xargs kill -9
```

---

## Current Code Structure

The only built module is the **BOM Intelligence Agent** at `agents/bom_intelligence/`:

| File | Role |
|---|---|
| `models.py` | Pydantic data models: `BOMComponent`, `BOMData`, `SubstituteInfo`, `ComponentRisk`, `SKURiskReport` |
| `bom_fetcher.py` | Parses Propel Excel exports → `BOMData`; contains `PropelAPIClient` stub |
| `bom_graph_builder.py` | Builds NetworkX `DiGraph` with `USES` and `SUBSTITUTE` edges |
| `substitute_analyzer.py` | Classifies each primary component's substitute risk (HIGH/MEDIUM/LOW) using manufacturer + region + lifecycle viability |
| `risk_engine.py` | Aggregates component risks into `SKURiskReport` with weighted SKU score (0–100) |
| `database.py` | SQLAlchemy ORM (`DBComponent`, `DBRiskScore`); gracefully degrades if no DB |
| `api.py` | FastAPI app; serves endpoints + static `index.html`; holds in-memory BOM/report cache |
| `streamlit_app.py` | Streamlit visual dashboard (gauge chart, filterable component table) |

**Phase 1 → Phase 2 migration notes (in-code TODOs):**
- `bom_graph_builder.py`: Replace NetworkX with Neo4j for multi-level BOMs and cross-SKU where-used
- `database.py`: Add Alembic for schema migrations
- `bom_fetcher.py`: Implement `PropelAPIClient.fetch_bom()` once Propel OAuth2 credentials available
- `api.py`: Replace in-memory cache with DB-backed reads once PostgreSQL is active

---

## System Architecture

```
React Dashboard
       |
    FastAPI
       |
  -------------------------
  |           |           |
Agent Engine  Risk Engine  Copilot
(LangGraph)   (Python)     (LLM)
  |
  --------------------------------
  |              |               |
PLM API   SiliconExpert API   News APIs

Database Layer
  - PostgreSQL
  - Neo4j (Graph)
  - Vector DB
```

## Planned Agents

The Agent Engine (LangGraph) orchestrates specialized agents running continuously (not batch):

- **BOM Ingestion Agent** — pulls multi-level BOM hierarchy from Propel PLM via API
- **Supplier Risk Agent** — monitors supplier health, financial signals, news
- **Compliance Agent** — screens for regulatory/ESG changes affecting parts or suppliers
- **Logistics Agent** — tracks freight, port disruptions, lead time changes
- **Demand/Environmental Agent** — monitors geopolitical events, climate signals
- **Risk Scoring Engine** — aggregates agent outputs into a unified risk index
- **Copilot/Narrative Agent** — generates human-readable summaries and prescriptive recommendations (LLM-based)
- **Q&A Interface** — natural language querying over risk state for non-technical stakeholders

## Key Integration Points

- **Propel PLM API** — source of BOM data (multi-level hierarchy, part-supplier relationships)
- **SiliconExpert API** — component/supplier intelligence data
- **News APIs** — external risk signal feeds
- **Dashboard** — React frontend with risk scoring UI and alerts for supply chain leadership

## POC Scope

6-8 week proof-of-concept targeting:
- One product family / BOM hierarchy
- 2-3 risk domains
- Deliverables: data pipeline (Propel -> Risk Engine), risk dashboard, narrative Q&A interface, prescriptive recommendations

## Tech Stack

- **Frontend**: React dashboard
- **Backend API**: FastAPI
- **Agent Orchestration**: LangGraph
- **Risk Engine**: Python
- **Copilot/Narrative**: LLM via Claude API (`claude-sonnet-4-6` or `claude-opus-4-6`)
- **Databases**: PostgreSQL (relational), Neo4j (graph — BOM/supplier relationships), Vector DB (semantic search)

## Success Metrics

- Risk detection latency reduction (baseline days -> target minutes/hours)
- % of relevant risks identified pre-disruption
- Leadership dashboard adoption

---

## BOM Intelligence Agent — Specification

The BOM Intelligence Agent is the **foundation of the entire platform**. All other agents (lifecycle, supplier, compliance) depend on it because it converts raw PLM BOM data into a structured intelligence model.

> **Critical note:** This org models alternates as separate BOM-level substitute items (not AML-level). The agent must handle `Item-A → Substitute → Item-B` relationships, not MPN-level AML alternates.

### Purpose

Transform raw PLM BOM data into actionable supply chain intelligence.

**Input** — Raw Propel PLM BOM:
```
SKU-A
├─ Item-1 (MPN-AAA)
├─ Item-2 (MPN-BBB)
│    └ Substitute → Item-3 (MPN-CCC)
└─ Item-4 (MPN-DDD)
```

**Output** — Structured intelligence:
```
SKU Risk Indicators
Total components: 16
Single source components: 7
Components with substitutes: 9
Top Risk Drivers:
  7/16 components are single source (44% of BOM)
  4 components have weak substitutes (same manufacturer or region)
  2 components have at-risk lifecycle (EOL / LTB / NRND)
  9 components are safety or field-critical
  4 components are unique to Samsara
```

### 5 Core Analysis Functions

**Function 1 — Single Source Detection**
```python
if substitutes_count == 0 AND multiple_source_status == "Single":
    → Confirmed single source (HIGH structural risk)
if substitutes_count == 0 AND multiple_source_status == "Multi":
    → No BOM substitute listed — verify with sourcing
```
Output: `single_source_count / total` → risk ratio (executive metric)

**Function 2 — Substitute Quality Check**
Classify substitute coverage for each primary component:

| Scenario | Risk Level | Notes |
|---|---|---|
| No substitute | HIGH | base score 70 |
| Substitute exists, same manufacturer OR same region | MEDIUM | base score 40 — weak substitute |
| Substitute exists, different manufacturer AND different region | LOW | base score 10 — strong substitute |
| Substitute exists but ALL substitutes are EOL/LTB/NRND | MEDIUM | viable substitute count = 0 |

> **Viable substitute rule:** EOL/LTB/NRND substitutes are excluded from LOW classification. A substitute that is itself at-risk lifecycle provides no real coverage. The substitute's lifecycle phase is flagged in risk drivers.

**Function 3 — Portfolio Dependency (Where-Used)**
Map which SKUs depend on each component. Risk amplification: if a component goes EOL, all dependent SKUs are impacted.
```cypher
MATCH (c:Component)<-[:USES]-(sku:SKU) RETURN sku
```
API: `GET /component/{item_id}/where-used`

**Function 4 — Criticality Amplification**
Parts marked `Field`, `Safety`, or `Field & Safety` increase risk severity:
- Component score modifier: +15
- Counted toward SKU-level criticality weight

**Function 5 — BOM Risk Scoring**
Per-SKU risk score (0–100), weighted ratios of component counts:

| Factor | SKU Weight | Component Base/Modifier |
|---|---|---|
| Single source (no substitute) | 60 | base 70 |
| Weak substitute (same mfr or region) | 15 | base 40 |
| At-risk lifecycle (EOL / LTB / NRND) | 10 | +15 modifier |
| Critical parts (Field / Safety / Field & Safety) | 10 | +15 modifier |
| Unique to Samsara | 5 | +10 modifier |

SKU risk level thresholds: CRITICAL ≥ 80 | HIGH ≥ 55 | MEDIUM ≥ 30 | LOW < 30

Additional factors (not yet active, to be added): supplier concentration, manual risk flags.

### Samsara-Unique Parts
If `Unique to Samsara = Yes`, the component has no ecosystem alternatives if discontinued. This increases component score by +10 and contributes to the SKU's unique_to_samsara weight.

### Internal Microservices

| Service | Responsibility | Libraries |
|---|---|---|
| BOM Extractor | Pull data from Propel PLM API | Python, FastAPI |
| BOM Graph Builder | Build BOM network in Neo4j | networkx, neo4j driver |
| Substitute Analyzer | Detect alternate coverage (mfr + region + lifecycle) | — |
| Single Source Detector | Identify vulnerable components | — |
| Where Used Engine | Cross-SKU dependency mapping | — |
| Risk Scoring Engine | Convert component risk → SKU score | — |

### Data Flow

```
Propel PLM API → BOM Extractor → Graph Builder → Substitute Analyzer
→ Single Source Detector → Where Used Engine → Risk Scoring Engine → Risk API
```

### FastAPI Endpoints

```
POST /bom/load                       # Load a BOM from Excel filepath
GET  /risk/skus                      # List all loaded SKUs with summary scores
GET  /risk/sku/{sku_id}              # Full risk report for a SKU
GET  /risk/components/high           # HIGH-risk components across loaded SKUs
GET  /component/{item_id}/where-used # Cross-SKU dependency
GET  /health                         # Health check
```

### Open Design Question

Substitute chain modeling — current approach is flat (non-chained):
```
Item-A → Substitute → Item-B
```
If chained: `Item-A → Item-B → Item-C` — treat as chain or multi-alternate?
**This decision changes the graph algorithm design.** Resolve before scaling to multi-level BOMs.

---

## Sample BOM Data — Schema & Structure

Two sample files are available in `Project Docs/`:

| File | SKU | Purpose |
|---|---|---|
| `Sample BOM.xlsx` | `310-00-00183` | Real Propel PLM export — no Country of Origin / MOQ / Unique to Samsara columns |
| `Sample BOM Extended.xlsx` | `310-00-00200` | Synthetic dataset covering all analysis dimensions (16 primary, 9 substitutes) |

### Extended Sample — Scenario Coverage

| Scenario | Component(s) | Expected Score |
|---|---|---|
| Single source + Safety + Unique to Samsara | MCU, GPS, Secure Element | 95 (CRITICAL) |
| Single source + Field & Safety + Unique | PMIC, Secure Element | 95 (CRITICAL) |
| Single source + Field + NRND/EOL lifecycle | RF PA, 4G Modem | 100 (CRITICAL) |
| Single source, no modifiers | USB-C Connector | 70 (HIGH) |
| Weak sub (same region) + Field criticality | DRAM Samsung→SK Hynix (both Korea) | 55 (HIGH) |
| Weak sub (same region) | NOR Flash (Taiwan→Taiwan) | 40 (MEDIUM) |
| Weak sub (same manufacturer) | Voltage Reference (TI→TI) | 40 (MEDIUM) |
| Strong sub (diff mfr + diff region) + Safety | IMU (Germany→Japan) | 25 (MEDIUM) |
| Strong sub (diff mfr + diff region) | Ethernet PHY (Taiwan→USA) | 10 (LOW) |

### Full Column Schema

| Column | Description |
|---|---|
| `Level` | BOM depth: `0` = SKU, `1` = component |
| `Item Number` | Internal Propel item ID (e.g. `350-00-03372`) |
| `Substitute For` | **If populated**, this row is a substitute for the item number listed here |
| `Is Substitute` | Boolean flag — `True` if this row is a substitute item |
| `Description` | Component description / part name |
| `Manufacturer` | Manufacturer name |
| `Manufacturer Part Number` | Manufacturer's MPN |
| `Lifecycle Phase` | `ACTIVE`, `EOL` (End of Life), `LTB` (Last Time Buy), `NRND` (Not Recommended for New Designs) |
| `Criticality Type` | `Field`, `Safety`, `Field & Safety`, `Function`, `NA`, or empty |
| `Country of Origin` | Country where the component is manufactured |
| `Lead Time (Days)` | Supplier lead time |
| `MOQ` | Minimum Order Quantity |
| `Multiple Source Status` | `Single` or `Multi` — sourcing team's assessment |
| `Unique to Samsara` | `Yes` / `No` — no ecosystem alternatives exist |
| `Reference Designators` | PCB reference designator(s) |
| `Quantity` | Qty used in this BOM |
| `Vendor` / `Vendor Part#` | Sourcing vendor info |
| `Flag Risk Review` | Manual risk flag |

### Substitute Relationship Logic

> **Critical:** A row with a value in `Substitute For` means: "the item in `Item Number` is the substitute FOR the item in `Substitute For`."

```
Primary item:   350-00-03372  (Is Substitute = False, Substitute For = None)
Substitute row: 350-00-00353  (Is Substitute = True,  Substitute For = 350-00-03372)
                ↑ this item IS the substitute FOR 350-00-03372
```

Real examples from `Sample BOM.xlsx`:
```
350-00-00353  →  substitute for  350-00-03372  (NMOS transistor, MCC → Diodes Inc.)
350-00-03466  →  substitute for  355-00-00010  (32MHz crystal, TXC → Diodes Inc.)
350-00-03460  →  substitute for  350-00-03316  (MEMS mic, SYNTIANT SPH0141 → SPH0641)
350-00-03462  →  substitute for  350-00-03342  (NOR Flash 64Mb, Winbond → Macronix)
350-00-03465  →  substitute for  350-00-03306  (55.2MHz crystal, TXC → NDK)
350-00-03463  →  substitute for  350-00-00588  (1uF MLCC 0201, Walsin → Murata)
350-00-03739  →  substitute for  350-00-03356  (2.2uF MLCC 0201, Walsin → Yageo)
350-00-03461  →  substitute for  350-00-03375  (10uH inductor, TDK → GOTREND)
350-00-03740  →  substitute for  350-00-03377  (battery spring, WNC variant)
350-00-03467  →  substitute for  350-00-03369  (Schottky diode, Panjit → LITEON)
350-00-03464  →  substitute for  350-00-03354  (10uF MLCC 0402, Taiyo → Darfon)
```

### Agent Parsing Rules

1. **To find all substitutes for a component:** find rows where `Substitute For == component_item_number`
2. **To detect single source:** primary component rows where no other row has `Substitute For == this item number`
3. **Substitute quality — same manufacturer:** compare `Manufacturer` of primary vs substitute → MEDIUM if same
4. **Substitute quality — same region:** compare `Country of Origin` of primary vs substitute → MEDIUM if same (only applied when both have known origin; unknown origin does not penalise)
5. **Substitute viability:** substitutes with `Lifecycle Phase` in `EOL`, `LTB`, `NRND` are excluded from LOW classification; if ALL substitutes are at-risk, the primary is MEDIUM
6. **Lifecycle risk flags:** `EOL`, `LTB`, `NRND` on the PRIMARY → add +15 to component score, count toward SKU lifecycle weight. `ACTIVE` = no risk.
7. **Criticality amplification:** `Criticality Type` in `Field`, `Safety`, `Field & Safety` → add +15 to component score
8. **Samsara-unique:** `Unique to Samsara = Yes` → add +10 to component score
