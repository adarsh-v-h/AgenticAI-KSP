# MIGRATE STEP 4 — Graph, Media, Execution, and Frontend

> Run this file last. It covers the network graph decision, evidence media, migration execution order, frontend impact, and the final checklist.

## 1. Graph model decision

`case_relationships` is not part of the official KSP schema. Choose one of two options:

### Option A — Compute relationships from official data (recommended)

Derive graph links from existing tables:

- Co-accused: same `CaseMasterID` in `Accused`
- Repeat offender: identical `AccusedName` across multiple `CaseMasterID`
- Similar crime pattern: same `CrimeMinorHeadID` and same `PoliceStationID`

This avoids inventing a new table and stays faithful to the official schema.

### Option B — Keep `case_relationships` as a local extension

If you keep it, repoint its foreign keys:

- `fir_id` → `case_master_id`
- `accused_id` → `AccusedMasterID`

Mark this clearly in code comments as a local performance/graph cache, not official KSP schema.

## 2. Evidence media treatment

`evidence_media` is also not in the official diagram. The recommended approach is:

- keep it as a local extension
- rename `fir_id` to `case_master_id`
- use `CaseMasterID` as the FK target

This preserves the media viewer feature without pretending the table is part of the official schema.

## 3. Migration execution order

Run these steps in order.

1. Back up the current database.
2. Create a new migration database.
3. Apply `MIGRATE_STEP1.md` DDL.
4. Apply `MIGRATE_STEP2.md` DDL.
5. Update `.env` to point at the new database.
6. Run the rewritten seed script.
7. Verify counts in the new database.
8. Rewrite `schema_catalog.py`.
9. Rewrite few-shot examples and prompt rules.
10. Add BIT normalization in `db/connection.py`.
11. Update `network_builder.py` for the graph model.
12. Update `evidence_media` FK if keeping it.
13. Update all backend modules and routers.
14. Test login and chat flow.
15. Update frontend field references.

## 4. Frontend impact

The frontend should require minimal changes if backend JSON fields remain consistent. Update only the places that explicitly expect old field names.

### Likely files to update

- `frontend/src/components/MessageBubble.jsx`
- `frontend/src/components/MediaViewer.jsx`
- `frontend/src/components/TableRenderer.jsx`
- any components or helpers that look for `fir_id`, `case_type`, `investigating_officer_id`, or legacy route params

### What should stay the same

- user-visible names like `Mahesh Gowda`
- flow of chat and graph actions
- media viewer behavior if `evidence_media` stays supported

## 5. Final checklist

- [ ] New DDL applied successfully to a fresh database
- [ ] Seed script rewritten and verified
- [ ] Schema catalog updated for the new tables
- [ ] Few-shot examples rewritten
- [ ] SQL prompt rules updated
- [ ] BIT normalization added
- [ ] Network graph rebuilt without `case_relationships`
- [ ] Evidence media pointed at `CaseMasterID` if kept
- [ ] Backend code updated for all old references
- [ ] Login/auth still works
- [ ] Chat query generation still works
- [ ] Frontend special-case field names updated
- [ ] Migration run order completed

## 6. What this migration does not do

- Does not implement deferred tables such as `CrimeHeadActSection` or `ChargesheetDetails`
- Does not attempt a complete legal schema rewrite beyond the core case and demo needs
- Does not change the voice pipeline, auth system design, or Catalyst integration
- Does not invent new official schema tables beyond `evidence_media` if kept as a local extension
