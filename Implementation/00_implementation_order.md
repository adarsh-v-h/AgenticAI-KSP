# Implementation Order

## Recommended sequence (fastest impact first):

| Order | Feature | Effort | Why this order |
|-------|---------|--------|----------------|
| **1** | Rule Engine Before LLM | 30 min | Zero-risk, instant user-visible improvement (greetings respond in 0ms instead of 4s). Touches only 2 files, no prompt changes. |
| **2** | Crime Forecasting & Early Warning | 2 hrs | Fills a **missing hackathon requirement** — judges will look for this. Backend + frontend in one shot, same patterns as existing analytics. |
| **3** | Dynamic Few-Shot Retrieval | 45 min | Improves SQL generation accuracy for diverse question phrasings. Small change, big quality improvement. No user-facing UI needed. |
| **4** | Conversation State Engine | 1.5 hrs | Largest refactor of the four. Improves follow-up accuracy but requires careful testing since it changes what the LLM sees in its prompt. Do last so other features are stable. |

## Total estimated effort: ~5 hours

## Dependencies between them: None

All four are independent — they touch different files and can be implemented in any order without conflicts. The sequence above is purely optimized for "fastest demo-ready impact."

## After implementation:

- Remove the discarded proposals from `Support Documents/Advanced_System_Design_Recommendations.md` (or delete the file entirely — it's a planning doc, not active code)
- Update `miss-features-report.md` to mark Crime Forecasting as implemented
- Run full test suite to verify no regressions
