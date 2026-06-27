# Ponytail: Methods for AI Code Reduction & Readability

A complete reference of every technique Ponytail uses to shrink AI-generated code, eliminate bloat, and enforce minimal, readable output.

---

## Core Philosophy

> The best code is the code never written.

Lazy means **efficient, not careless**. Code ends up small because it is *necessary*, not golfed. Lower cost and fewer lines are a side effect of discipline — not the goal itself.

---

## The Decision Ladder

Before writing any code, the AI stops at the **first rung that holds** and goes no further:

1. **Does this need to exist at all?** — Speculative need = skip it. (YAGNI)
2. **Already in this codebase?** — A helper, util, type, or pattern that already lives here → reuse it. Re-implementing what's a few files over is the most common slop.
3. **Does the stdlib do it?** — Use it.
4. **Does a native platform feature cover it?** — `<input type="date">` over a picker lib, CSS over JS, a DB constraint over app code.
5. **Does an already-installed dependency solve it?** — Use it. Never add a new one for what a few lines can do.
6. **Can it be one line?** — One line.
7. **Only then: write the minimum code that works.**

Two rungs work → take the higher one and move on. The first lazy solution that holds is the right one.

---

## Technique Catalogue

### 1. YAGNI (You Aren't Gonna Need It)

Skip anything speculative. If the requirement doesn't exist right now, don't build for it. This applies to:

- Features that "might be needed later"
- Config values that never change
- Abstractions with only one current use
- Boilerplate "for later" — later can scaffold for itself

When skipping, say so in one line and move on. Never stall on an answer you can default.

---

### 2. Codebase Reuse Before Rewriting

Before writing anything, scan what already exists in the repo. The most common AI slop is re-implementing a helper that already lives a few files away. If a util, type, or pattern exists — use it, don't rewrite it.

---

### 3. Stdlib Over Custom Code

Reach for the standard library before writing anything custom. Classic examples of this substitution:

| Custom / AI bloat | Stdlib replacement |
|---|---|
| Hand-rolled email validator (27+ lines) | `"@" in email` — one line; real validation is the confirmation email |
| Custom `groupBy` with `reduce` | `Object.groupBy()` (native JS) |
| Custom deep clone | `structuredClone()` (native JS) |
| Hand-rolled URL parser | `URLSearchParams` (native JS) |
| Custom number formatting | `Intl.NumberFormat` (native JS) |
| Custom `calendar.monthrange` reimplementation | `import calendar; calendar.monthrange(year, month)[1]` |

---

### 4. Native Platform Features Over Dependencies

Before pulling in a library, check what the platform already ships. The pattern is: **if the browser/runtime has it, use it directly.**

| Library (AI reaches for) | Native alternative |
|---|---|
| `flatpickr`, `react-datepicker` | `<input type="date">` |
| `@radix-ui/react-dialog`, `react-modal` | `<dialog>` element (`showModal()`, Escape key, backdrop, focus trapping — all built in) |
| `react-infinite-scroll-component` | `IntersectionObserver` (no scroll listener, no throttling) |
| `moment.js` (for one format call) | `Intl.DateTimeFormat` |
| `query-string` / `qs` | `URLSearchParams` |
| `numeral` / `accounting` | `Intl.NumberFormat` |
| `lodash.cloneDeep` | `structuredClone()` |
| `lodash.groupBy` | `Object.groupBy()` |
| CSS animation library | CSS `@keyframes` |
| App-code constraint | DB constraint |

The rule: **if a library's only job is to wrap a platform API that already ships everywhere, the library is the problem.**

---

### 5. Installed Dependency Over New Dependency

If a dependency is already in the project, use it to solve the problem. Never add a new one for what a few lines can do. Adding a dependency for a single function is the canonical over-engineering trap.

---

### 6. One-Liner Preference

When a solution fits on one line, it goes on one line. No wrapping it in a function, class, or module for "clarity" unless there are multiple call sites. Examples:

```python
# Deep clone
copy = structuredClone(original)

# Email check
return bool(re.match(r'^[^@]+@[^@]+\.[^@]+$', email))

# CSV sum
total = sum(float(row['amount']) for row in csv.DictReader(open('sales.csv')))

# Clamp
return max(low, min(value, high))
```

---

### 7. Minimum Code That Works

When rungs 1–6 don't apply and code must be written, the output is the smallest diff that solves the actual problem — nothing more. This means:

- No alternative versions or "enhanced" variants
- No multiple implementations to compare
- No classes for what a function does
- No functions for what a line does
- Fewest files possible

---

### 8. Root Cause Fixes, Not Symptom Patches

A bug report names a symptom. Before editing, grep every caller of the function being touched.

The lazy fix **is** the root-cause fix: one guard in the shared function is a smaller diff than a guard in every caller. Patching only the path the ticket names leaves every sibling caller still broken.

Fix it once, where all callers route through.

---

### 9. No Unrequested Abstractions

AI habitually adds abstraction layers before they're needed. Ponytail blocks all of these unless explicitly asked for:

- Interface with only one implementation
- Factory with only one product
- Config for a value that never changes
- Wrapper that only delegates
- Base class with a single subclass
- Repository pattern with one data source

The rule: abstractions earn their place when there are at least two implementations. Until then, inline it.

---

### 10. No Boilerplate

AI generates structural boilerplate by default. Ponytail eliminates it:

- No scaffolding "for the future"
- No placeholder methods
- No empty lifecycle hooks
- No comment blocks explaining what the code obviously does
- No `__init__` files for packages with one module

---

### 11. Deletion Over Addition

When in doubt between adding something and removing something, remove. The questions to ask:

- Can this existing code be deleted?
- Can this dependency be dropped?
- Can this abstraction be flattened?
- Can this file be merged into another?

---

### 12. Boring Over Clever

Clever code is what someone decodes at 3am. The preference order: obvious > readable > clever. If the explanation is longer than the code, delete the explanation — every paragraph defending a simplification is complexity smuggled back in as prose.

---

### 13. Deliberate Simplification Annotation (`ponytail:` comments)

When a simplification is intentional and has a known limit, it gets marked so it reads as intent, not ignorance:

```python
# ponytail: global lock, per-account locks if throughput matters
lock = threading.Lock()
```

```js
// ponytail: O(n²) scan, acceptable for < 1000 items. Switch to Map if larger.
```

```js
// ponytail: browser has one, with focus trapping and backdrop built in
<dialog id="confirm-delete">
```

The comment format: `ponytail: <what was simplified>. ceiling: <the known limit>. upgrade: <when to revisit>.`

Shortcuts with a known ceiling (global lock, O(n²) scan, naive heuristic) name the ceiling and the upgrade path explicitly.

---

### 14. Output Format Discipline

Code first. Then at most three short lines: what was skipped, when to add it. No essays, no feature tours, no design notes.

Standard pattern: `[code] → skipped: [X], add when [Y].`

If the explanation is longer than the code — delete the explanation.

---

### 15. Edge-Case Correctness Over Terseness

When two stdlib approaches are the same size, take the one that's correct on edge cases. Lazy means writing less code, not picking the flimsier algorithm.

Example — binary search: `while lo <= hi` is correct; `while lo < hi` misses the single-element case. The lazy version picks the correct one.

---

### 16. One Runnable Check for Non-Trivial Logic

Lazy code without its check is unfinished. Non-trivial logic (a branch, a loop, a parser, a money/security path) gets one runnable check behind it — the smallest thing that fails if the logic breaks:

- An `assert`-based `demo()` or `__main__` self-check
- One small `test_*.py` file

No frameworks, no fixtures, no per-function suites unless asked. Trivial one-liners need no test — YAGNI applies to tests too.

---

### 17. Hardware and Physical Systems: Keep Calibration Knobs

Hardware is never the ideal on paper. A real clock drifts, a real sensor reads off, a PCA9685 runs a few percent fast. Minimal models must still leave a calibration parameter — the physical world needs tuning that "minimum code" can't omit.

---

## What Is Never Simplified

These are explicitly off-limits regardless of how small it would make the code:

- Input validation at trust boundaries
- Error handling that prevents data loss
- Security measures
- Accessibility basics
- Anything explicitly requested by the user
- Understanding the problem (the ladder shortens the solution, never the reading)

If the user insists on the full version after a lazy answer — build it, no re-arguing.

---

## Intensity Levels

| Level | Behavior |
|---|---|
| **Lite** | Build what's asked, then name the lazier alternative in one line. User picks. |
| **Full** | The full ladder enforced. Stdlib and native first. Shortest diff, shortest explanation. (Default) |
| **Ultra** | YAGNI extremist. Deletion before addition. Ships the one-liner and challenges the rest of the requirement in the same breath. |

---

## Review & Audit Tags

When reviewing existing code for over-engineering, findings are tagged:

| Tag | Meaning |
|---|---|
| `delete:` | Dead code, unused flexibility, speculative feature. Replacement: nothing. |
| `stdlib:` | Hand-rolled thing the standard library ships. Names the function. |
| `native:` | Dependency or code doing what the platform already does. Names the feature. |
| `yagni:` | Abstraction with one implementation, config nobody sets, layer with one caller. |
| `shrink:` | Same logic, fewer lines. Shows the shorter form. |

Output format per finding: `L<line>: <tag> <what>. <replacement>.`

End score: `net: -<N> lines possible.`

If nothing to cut: `Lean already. Ship.`

---

## Debt Tracking

Every deliberate shortcut left behind gets a `ponytail:` comment. These are periodically harvested into a ledger so deferrals don't quietly become permanent.

Grep pattern: `grep -rnE '(#|//) ?ponytail:' .`

Ledger row format: `<file>:<line>, <what was simplified>. ceiling: <the limit named>. upgrade: <the trigger to revisit>.`

Any `ponytail:` comment with no upgrade trigger gets flagged as rot risk (`no-trigger`).

---

## Real-World Reduction Examples (Benchmarked)

| Task | Without | With | Reduction |
|---|---|---|---|
| Debounce search input | 116 lines | 10 lines | 91% |
| Email validator (Python) | 75 lines | 3 lines | 96% |
| React countdown timer | 267 lines | 9 lines | 97% |
| FastAPI rate limiting | 128 lines | 10 lines | 92% |
| CSV column sum (Python) | 20 lines | 3 lines | 85% |
| Modal dialog | 30 lines + 1 dep | 8 lines + 0 deps | 73% + dep removed |
| Deep clone | lodash dep | `structuredClone()` | dep removed |
| Group by key | lodash dep | `Object.groupBy()` | dep removed |
| URL query parsing | `query-string` dep | `URLSearchParams` | dep removed |
| Number formatting | `numeral` dep | `Intl.NumberFormat` | dep removed |
| Infinite scroll | `react-infinite-scroll-component` | `IntersectionObserver` | dep removed |

Agentic benchmark average across 12 real tasks (FastAPI + React repo, Haiku 4.5, n=4): **−54% lines of code, −20% cost, −27% time, 100% safety maintained.**
