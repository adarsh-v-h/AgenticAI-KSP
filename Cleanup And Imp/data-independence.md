# Data Independence System

A 3-step system. Run them in order, once. After that, only Step 3 repeats whenever you make big changes.

---

## Step 1 — Clean Up First (Run Once)

**What it does:** Finds and removes every parameter a function receives but never uses, and every return value no caller ever reads. This must happen before Step 2, or you'll be locking in bad contracts.

**Paste this into Claude Code:**

```
Audit every function in this codebase (Python + JavaScript/TypeScript files).

For each function, check two things:

1. UNUSED PARAMETERS — a parameter is declared in the signature but never referenced in the function body.
2. UNUSED RETURN VALUES — a value is returned by the function, but every call site either ignores it entirely (no assignment, no chaining, no conditional on it).

Rules before touching anything:
- Trace the full function body before marking a param unused. A param passed into a nested call or used in a string/log still counts as used.
- For return values, check EVERY call site in the codebase, not just one. If even one caller uses the return value, it is NOT unused.
- Do NOT touch: __init__, constructors, interface implementations, overridden methods, callbacks passed to external libraries, public API functions exported from index files, anything with a # keep or // keep comment.
- Do NOT remove a param if the function signature is part of an interface contract or used with **kwargs / ...args spread.

For Python: remove unused params from the signature and their corresponding arguments at every call site. For unused returns, change `return x` to just `return` or remove the return entirely if the function naturally falls through.
For JavaScript/TypeScript: same. If a function is async and returns an unused promise, leave it — removing async has side effects.

After changes, run a quick grep to confirm no remaining references to the removed names exist in unexpected places.

Output a summary when done:
- How many params removed, from which files
- How many return values removed, from which files
- Any functions you SKIPPED and why
```

---

## Step 2 — Lock the Contracts (Run Once After Step 1)

**What it does:** Adds inline contract comments above every function AND generates a `CONTRACTS.md` file. This is your "black box" layer — the interface is now documented and visible.

**Save this as `contract-lock.md` in your repo root, then paste the prompt below into Claude Code:**

### The instruction file (`contract-lock.md`)

```markdown
# Contract Rules

A function contract has exactly three parts:
1. TAKES — every parameter, its type, and what it represents
2. RETURNS — every return value, its type, and what it represents  
3. THROWS/RAISES — any error it can raise intentionally (skip if none)

Contract comments go directly above the function definition, every time.
They are never inside the function body.

Format for Python:
# CONTRACT
# takes:  param_name (type) — what it is
# returns: (type) — what it is
# raises:  ErrorType — when

Format for JavaScript/TypeScript:
// CONTRACT
// takes:  param_name (type) — what it is
// returns: (type) — what it is
// throws:  ErrorType — when

If a function takes no parameters, write: takes: nothing
If a function returns nothing, write: returns: nothing

These comments are the source of truth for the interface.
Internal implementation can change freely — these lines must not.
```

### The prompt to run:

```
Read contract-lock.md from the repo root.

Then do the following across all Python and JavaScript/TypeScript files:

STEP A — Add inline contract comments
For every function (including methods inside classes):
- Add a CONTRACT comment block directly above the function definition, following the format in contract-lock.md exactly.
- Infer types from usage, type hints, JSDoc if present, or surrounding code. If a type is genuinely ambiguous, write: (any).
- Be precise about what the parameter represents, not just its name. Bad: "param_name (str) — the string". Good: "user_id (str) — the unique identifier for a registered user".
- Do not add contracts to: lambdas, one-line arrow functions, private dunder methods (__str__, __repr__, etc.) unless they have real logic.

STEP B — Generate CONTRACTS.md
Create a file called CONTRACTS.md in the repo root.

Structure:
# Function Contracts

## <filename>

### function_name
- **Takes:** param (type) — description
- **Returns:** (type) — description  
- **Raises:** ErrorType — when  *(omit if none)*

One section per file, one block per function, alphabetically sorted within each file.
At the top of CONTRACTS.md, add a one-line summary of the total count:
"N functions across M files."

Do not include lambdas or private dunder methods here either.
```

---

## Step 3 — Keep It Updated (Run After Every Big Change)

**What it does:** Re-checks that contracts still match reality after you've changed internals. This is the prompt you run repeatedly.

**Paste this into Claude Code whenever you refactor something significant:**

```
Read CONTRACTS.md and the contract-lock.md format rules.

Do three things:

1. DRIFT CHECK
   For every function that has a CONTRACT comment, compare what the comment says to what the code actually does now.
   Flag any mismatch: wrong type, wrong param name, return value changed, new raise added.
   List mismatches as: file:line | function | what drifted

2. MISSING CONTRACTS
   Find any function that does NOT have a CONTRACT comment above it.
   These are new functions added since the last run.
   Add the contract comment to each one, following contract-lock.md format.

3. UPDATE CONTRACTS.md
   Regenerate only the sections of CONTRACTS.md that changed.
   Do not rewrite sections that are still accurate.
   Update the total count line at the top.

Do not change any function logic. Contracts only.
```

---

## How This Protects Cross-Language Rewrites

When you rewrite a Python function in Go, Rust, or C++ later, the workflow is:

1. Look up the function in `CONTRACTS.md` — that's your input/output spec.
2. Write the new implementation in the other language to match exactly those inputs and outputs.
3. Expose it via FFI, a subprocess call, or an HTTP endpoint — whatever bridge you're using.
4. Run **Step 3** on the Python/JS side to confirm the call site still matches the contract.

The contract comment and `CONTRACTS.md` entry do not change when you rewrite the internals. That's the whole point — the interface is frozen, only the engine changes.

---

## File Layout After Setup

```
your-repo/
├── contract-lock.md       ← format rules (Step 2 reads this)
├── CONTRACTS.md           ← generated, updated by Step 3
├── src/
│   ├── your_file.py       ← CONTRACT comments above every function
│   └── your_file.js       ← same
```
