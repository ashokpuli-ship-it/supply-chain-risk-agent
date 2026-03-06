# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Multi-Agent Supply Chain Risk Intelligence Platform** — an AI platform that integrates Propel PLM BOM data with real-time external signals (news, suppliers, logistics, compliance) to provide proactive risk detection and mitigation recommendations.

Phase 1 (POC) of the BOM Intelligence Agent is built and running. The `project docs/` folder contains the business case, requirements document, and sample BOM Excel file.

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

**Run Streamlit dashboard** (visual BOM risk UI)
```bash
cd agents/bom_intelligence
.venv/bin/streamlit run streamlit_app.py
```

On startup, both interfaces auto-load `project docs/Sample BOM.xlsx` if present. PostgreSQL is optional — the app runs in memory-only mode without it.

**Load a BOM via API**
```bash
curl -X POST "http://localhost:8000/bom/load?filepath=/abs/path/to/BOM.xlsx"
```

---

## Current Code Structure

The only built module is the **BOM Intelligence Agent** at `agents/bom_intelligence/`:

| File | Role |
|---|---|
| `models.py` | Pydantic data models: `BOMComponent`, `BOMData`, `ComponentRisk`, `SKURiskReport` |
| `bom_fetcher.py` | Parses Propel Excel exports → `BOMData`; contains `PropelAPIClient` stub |
| `bom_graph_builder.py` | Builds NetworkX `DiGraph` with `USES` and `SUBSTITUTE` edges |
| `substitute_analyzer.py` | Classifies each primary component's substitute risk (HIGH/MEDIUM/LOW) |
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
Total components: 132
Single source components: 37
Components with substitutes: 95
High Impact Risks:
  Item-4 → No substitute
  Item-2 → substitute but same manufacturer
  Item-7 → used in 9 SKUs
```

### 5 Core Intelligence Functions

**Function 1 — BOM Structure Parsing**
Build a machine-readable graph of the BOM using Neo4j.
```
(SKU) → USES → (Assembly) → USES → (Component) → SUBSTITUTE → (Component)
```
Node example: `{ type: component, mpn: ABC123, manufacturer: TI, lifecycle: Active }`

**Function 2 — Substitute Intelligence**
Classify substitute risk for each component:

| Scenario | Risk Level |
|---|---|
| No substitute | HIGH |
| Substitute, same manufacturer | MEDIUM |
| Substitute, different manufacturer | LOW |

**Function 3 — Single Source Detection**
```python
for component in BOM:
    if no substitute relationship exists:
        mark single source
# Output: single_source_count / total → risk ratio (executive metric)
```

**Function 4 — Where-Used Intelligence**
Map which SKUs depend on each component. Risk amplification: if a component goes EOL, all dependent SKUs are impacted.
```cypher
MATCH (c:Component)<-[:USES]-(sku:SKU) RETURN sku
```

**Function 5 — BOM Risk Scoring**
Per-SKU risk score (0–100):

| Risk Type | Weight |
|---|---|
| Single source | 5 |
| Same manufacturer substitute | 3 |
| Lifecycle risk (NRND/EOL) | 4 |
| Supplier concentration | 3 |

### Internal Microservices

Implement as modular Python services behind FastAPI:

| Service | Responsibility | Libraries |
|---|---|---|
| BOM Extractor | Pull data from Propel PLM API | Python, FastAPI |
| BOM Graph Builder | Build BOM network in Neo4j | networkx, neo4j driver |
| Substitute Analyzer | Detect alternate coverage | — |
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
GET /risk/sku/{sku_id}          # SKU-level risk summary
GET /risk/components/high       # All high-risk components
GET /component/{item_id}/where-used  # Cross-SKU dependency
```

### Open Design Question

Current substitute modeling:
```
Item-A → Substitute → Item-B
```
If chained: `Item-A → Item-B → Item-C` — should this be treated as:
- **Chain** (A has 1 alternate: B, which itself has 1 alternate: C), or
- **Multi-alternate** (A has 2 alternates: B and C)?

**This decision changes the graph algorithm design.** Resolve before building Function 2.


---

## Sample BOM Data — Schema & Structure

The file `project docs/Sample BOM.xlsx` is a real BOM exported from Propel PLM for SKU `310-00-00183` (UCT-COP,DIP,PCBA,VER.D). The same structure is returned by the Propel PLM API.

**Dataset stats:**
- 1 top-level SKU (Level 0)
- 121 primary components (Level 1, `Is Substitute = False`)
- 11 substitute items (Level 1, `Is Substitute = True`)
- 11 primary components have a substitute → 110 are single source (90.9%)

### Column Schema

| Column | Description |
|---|---|
| `Level` | BOM depth: `0` = SKU, `1` = component |
| `Item Number` | Internal Propel item ID (e.g. `350-00-03372`) |
| `Substitute For` | **If populated**, this row is a substitute for the item number listed here |
| `Is Substitute` | Boolean flag — `True` if this row is a substitute item |
| `Description` | Component description / part name |
| `Manufacturer` | Manufacturer name |
| `Manufacturer Part Number` | Manufacturer's MPN |
| `Lifecycle Phase` | `Production` or `Development` |
| `Criticality Type` | `Function`, `NA`, or empty |
| `Reference Designators` | PCB reference designator(s) |
| `Quantity` | Qty used in this BOM |
| `Lead Time (Days)` | Supplier lead time |
| `Vendor` / `Vendor Part#` | Sourcing vendor info |
| `Multiple Source Status` | Multi-source flag (currently unpopulated in sample) |
| `Is Secondary Source?` | Secondary source flag |
| `Flag Risk Review` | Manual risk flag |

### Substitute Relationship Logic

> **Critical:** A row with a value in `Substitute For` means: "the item in `Item Number` is the substitute FOR the item in `Substitute For`."

```
Primary item:   350-00-03372  (Is Substitute = False, Substitute For = None)
Substitute row: 350-00-00353  (Is Substitute = True,  Substitute For = 350-00-03372)
                ↑ this item IS the substitute FOR 350-00-03372
```

Real examples from the dataset:
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
3. **Same-manufacturer substitute risk:** compare `Manufacturer` of primary vs substitute row
4. **Lifecycle risk flags:** `Development` lifecycle = not yet production-qualified; treat with elevated risk
5. **Criticality = `Function`** marks functionally critical components (extra weight in risk scoring)
