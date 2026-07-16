# Missing Features Report

1 feature from the hackathon Feature List requires external data not present in our schema and cannot be implemented with current resources.

---

## 1. Financial Crime & Transaction Link Analysis (Feature #7)

**Required by Feature List:**
- Detect financial transactions linked to criminal activities
- Identify money trails and suspicious transaction networks
- Integrate with financial crime investigation workflows

**Current state:** Cannot be implemented without new schema + data.

- No financial transaction tables in `schema.sql` (no bank accounts, transaction records, money trails)
- The KSP database schema does not include financial data — it tracks FIRs, accused, victims, arrests, and case status
- Fraud cases mention monetary amounts in `BriefFacts` text but there's no structured financial data model

**Why it stays missing:**
- Requires entirely new tables (bank accounts, transactions, money flows)
- Requires synthetic financial data that doesn't exist in the KSP schema
- Would need a separate graph visualization for money trails
- This is the only feature that fundamentally cannot be built from existing data

**Workaround for demo:** The chatbot can answer questions like "Show me fraud cases" or "What's the total amount in fraud cases" by extracting amounts from BriefFacts via the LLM — this provides partial coverage without new infrastructure.

---

## Previously Missing (Now Implemented or Planned)

| Feature | Status |
|---------|--------|
| Crime Forecasting & Early Warning | Implementation plan ready at `Implementation/04_crime_forecasting_early_warning.md` |
| Sociological Crime Insights | ✅ Implemented (5 demographic endpoints + 5 dashboard panels) |
| PDF Export | ✅ Implemented (fpdf2, application/pdf) |
