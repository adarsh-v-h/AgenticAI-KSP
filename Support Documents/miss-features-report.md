# Missing Features Report

3 features from the hackathon Feature List are **completely absent** from the codebase. 1 additional feature has a partial implementation gap.

---

## 1. Financial Crime & Transaction Link Analysis (Feature #7)

**Required by Feature List:**
- Detect financial transactions linked to criminal activities
- Identify money trails and suspicious transaction networks
- Integrate with financial crime investigation workflows

**Current state:** Entirely absent.

- No financial transaction tables in `schema.sql` (no bank accounts, transaction records, money trails)
- No financial-related modules, pipelines, endpoints, or frontend components
- The only "financial" reference is in seed data — fraud case descriptions mention monetary amounts in `BriefFacts` text, but there's no structured financial data model

**What would be needed:**
- Schema: A `financial_transactions` table (or similar) linking accused/cases to bank accounts, transaction amounts, dates
- Backend: A pipeline module (e.g., `financial_analysis.py`) with functions to detect suspicious patterns, trace money flows between linked accused
- Backend: A router with endpoints like `GET /api/financial/transactions/{accused_id}`, `GET /api/financial/network/{case_id}`
- Frontend: A visualization component for money trails (could reuse the network graph pattern with vis-network)
- Data: Seed data with synthetic financial transactions

**Realistic scope:** This is a major feature requiring new schema + seed data + pipeline + router + frontend. If time is limited, a minimal version could extract monetary amounts from `BriefFacts` using the LLM and show them alongside case data — no new tables needed, just a pipeline function.

---

## 2. Crime Forecasting & Early Warning (Feature #8)

**Required by Feature List:**
- AI-driven identification of emerging crime patterns
- Generate early warning alerts for repeat crimes, gang activity, organized crime
- Predict potential crime hotspots

**Current state:** Entirely absent.

- No prediction/forecasting modules anywhere in the codebase
- No alert system or notification mechanism
- `trend_analytics.py` does **historical** pattern analysis (seasonal trends, MO clusters) but performs zero forward-looking prediction

**What would be needed:**
- Backend: A `forecasting.py` pipeline module using statistical methods (e.g., time-series extrapolation from monthly trends, or a simple "if crime count in station X increased >50% in last 3 months → flag as hotspot" heuristic)
- Backend: A router with endpoints like `GET /api/forecasting/hotspots`, `GET /api/forecasting/alerts`
- The forecasting doesn't need ML/deep learning — rule-based heuristics on existing trend data would satisfy the requirement (e.g., "stations where crime increased month-over-month for 3+ consecutive months")
- Frontend: An alerts panel or section in the analytics dashboard showing flagged stations/patterns

**Realistic scope:** Medium effort. The data already exists in `CaseMaster` with dates and stations. A rule-based module (200-300 lines) that queries recent trends and flags anomalies would satisfy the requirement without needing external ML models.

---

## 3. Sociological Crime Insights (Feature #4)

**Required by Feature List:**
- Analyze crime patterns using demographic attributes (age, gender, socio-economic background)
- Identify social risk factors influencing crime
- Correlate crime with urbanization, migration, economic stress, education

**Current state:** Entirely absent as a dedicated feature.

- The schema **does support** demographic queries: `ComplainantDetails` has `CasteID`, `ReligionID`, `OccupationID`, `GenderID`, `AgeYear`; `Accused` has `GenderID`, `AgeYear`; `Victim` has `GenderID`, `AgeYear`
- The NL2SQL pipeline can answer ad-hoc demographic questions ("how many accused are male?") since `schema_catalog.py` knows these columns
- However, there is **no purpose-built** sociological analysis module, endpoint, or dashboard panel
- No urbanization/migration/economic stress data exists in the schema (only occupation, caste, religion)

**What would be needed:**
- Backend: A `sociological_analytics.py` pipeline module with functions like:
  - `get_crime_by_age_group()` — buckets accused/victims by age ranges
  - `get_crime_by_gender()` — breakdown by gender across crime types
  - `get_crime_by_occupation()` — which occupations appear most in accused/complainant data
  - `get_demographic_risk_factors()` — cross-tabulation of crime type × demographic attributes
- Backend: A router with endpoints like `GET /api/analytics/demographics/age`, `GET /api/analytics/demographics/gender`, etc.
- Frontend: A new panel in `AnalyticsDashboard.jsx` or a separate demographic insights view

**Realistic scope:** Low-medium effort. The data is already there (seeded in `ComplainantDetails` with occupation/religion/caste). Just needs query functions + a router + a dashboard panel. Correlations with urbanization/migration/economic stress would require additional data not in the current schema — those sub-requirements can't be satisfied with what we have.

---