# memory.md — Research Coordinator Working State

Last updated: 2026-06-12

---

## Current State

Deployed and functional. **`origin`, `hf`, and the live Space are all in sync
at `3ed815b`** — pushed 2026-06-12 and confirmed `RUNNING` via the HF Space
runtime API (`sha: 3ed815ba29ad4d7f5806634252e30f099503e06b`). The
auto-continue-past-step-limit fix (`98c2a61`) and the rest of the
2026-06-09/06-12 eval-harness work are now live.

**This class of drift shouldn't recur**: `.github/workflows/sync-to-hf-space.yml`
(added 2026-06-12) force-pushes `origin/main` → `hf` on every push to `main`.
`origin` is now the source of truth — do not push directly to `hf`.

`HF_TOKEN` repo secret (write access to `anne-voigt/research_coordinator`)
was added 2026-06-13. **Not yet confirmed working**: the only Actions run so
far (`93056cf`, run
[27473037298](https://github.com/avoigt1121/research-coordinator/actions/runs/27473037298))
predates the secret and failed at the push step, as expected. No run has
happened since the secret was added — confirm by re-running that job from
the Actions tab, or by pushing anything to `main`.

---

## What Was Done (2026-06-12, this session)

- Added checkpoint/resume support to `eval/run_eval.py` (`b35af4d`): writes
  `_checkpoint_{bank}_raw.json` / `_checkpoint_{bank}_graded.json` after each
  question/grade, resumes by skipping already-completed/-graded IDs on
  restart, and deletes both checkpoints via `unlink(missing_ok=True)` once a
  full run + report finish successfully. New `eval/pilot_questions_10.json`
  (10-question subset) exercises the resume path on a faster bank.
- Recorded the 2026-06-09 16:53 full 18-question pilot eval run (`2950b95`):
  17/18 routing correct (OOS-002 misrouted to `direct`), quality 8 PASS /
  2 PARTIAL / 8 FAIL, 101.8 min total latency (avg 339.5s/question).
- Left `eval/results/20260610_154625_raw.json` and a leftover
  `_checkpoint_pilot_questions_10_raw.json` untracked — an
  interrupted/ungraded test of the new resume path against
  `pilot_questions_10` (resumed from `ANS-005` onward, no `_graded.json`/
  `_report.md`). Now gitignored (`eval/results/_checkpoint_*.json`). Safe to
  delete or re-run to completion.
- Closed the `hf`-vs-`origin` gap: pushed `origin main` and `hf main` to
  `3ed815b` (the memory.md-update commit). Confirmed via the HF Space runtime
  API that `anne-voigt/research_coordinator` rebuilt and is `RUNNING` at
  `sha: 3ed815ba29ad4d7f5806634252e30f099503e06b`.
- Added `.github/workflows/sync-to-hf-space.yml`: auto-syncs `origin/main` →
  `hf` (force-push) on every push to `main`, so the Space can't silently fall
  behind again. `origin` is now the documented source of truth; `hf` is a
  pure mirror. One-time setup remaining: add an `HF_TOKEN` repo secret (see
  "Current State").
- Investigated whether research-coordinator should get a `hf-dev`-style dev
  Space (DecoupleRpy_Agent has one). Findings: DecoupleRpy_Agent's `hf-dev`
  remote (`anne-voigt/Paper2Agent_decoupleRpy_dev`) is at `5e4f4cb`
  (2026-06-02) — 10 days and ~7 commits behind `origin`'s current `5dd994d`,
  and the HF API can no longer fetch its info unauthenticated. All of the
  2026-06-09/06-12 precompute-migration work shipped straight to `origin`
  (prod), bypassing it entirely — the dev-Space pattern appears to have
  fallen out of use. **Recommendation: skip a dev Space for
  research-coordinator** — it's a thin router with low blast-radius (per
  `CLAUDE.md`'s "if it went down, users could query the specialist directly"),
  and a second Space would add secret/promotion overhead that doesn't seem to
  be paying for itself even on the specialist side. Revisit if this repo
  starts shipping riskier changes (e.g., once a second specialist is wired
  up, per item 3 below).

---

## What Was Done (2026-06-09)

- `958bd60` — Added the DecoupleRpy-scoped eval harness (`eval/run_eval.py`,
  `eval/pilot_questions.json`, `eval/select_pilot.py`, `eval/README.md`):
  routing is graded automatically against `agents.yaml`; response quality is
  graded by an LLM judge against each question's `expected_behavior`. Also
  fixed a Python 3.9 type-syntax incompatibility in `router.py`/`gradio_ui.py`.
- `91eb0c1` — Added eval latency reporting + `eval/requirements.txt`; recorded
  the first full pilot run (`20260609_155729_*`); added working docs
  (`prompts/claude_code_add_datasets.md`,
  `prompts/claude_code_gui_dataset_selector.md`) and expanded root `CLAUDE.md`.
- `98c2a61` — **Auto-continue specialist agent past its step limit**
  (`router.py`, +50/-21): the coordinator now automatically resumes the
  DecoupleRpy specialist if it stops at LangGraph's step limit, instead of
  surfacing a truncated result to the user.
- `83b837e6` (pushed to `hf` same day, 15:16) — Added session save/load to the
  Gradio UI. This is the current `hf/main` HEAD — the 3 commits above (plus
  this session's 2) are not yet on `hf`.

---

## What Was Done (2026-06-02 and earlier)

- Added routing rules for capability/dataset questions (routes to specialist, not answered directly)
- Added Scientific Interpretation Rules to `coordinator_system_prompt` (hedged language, no unsupported clinical claims)
- Fixed result extraction: finds "Final Solution" message, skips HF log notice
- Fixed dispatch: two-step call — set query state via `/lambda`, then `/interact_with_agent`

---

## Known Issues / Next Steps

### 0. ~~`hf` Space behind `origin`/local `main`~~ — RESOLVED 2026-06-12
Pushed `origin` and `hf` to `3ed815b`; Space confirmed `RUNNING` at that sha.
Added `.github/workflows/sync-to-hf-space.yml` so `hf` auto-mirrors
`origin/main` on every push going forward (see "Current State"). `HF_TOKEN`
repo secret added 2026-06-13 — first successful run not yet confirmed (see
"Current State" for how to test).

### 1. Routing is keyword-based — fragile, but now has a regression test
**Partially addressed 2026-06-09** (`958bd60`): `eval/run_eval.py` +
`eval/pilot_questions.json` grade routing automatically against `agents.yaml`
for 18 DecoupleRpy-scoped questions. Latest run (2026-06-09 16:53, `2950b95`):
17/18 correct — one miss (OOS-002, a primer-design question, misrouted to
`direct` instead of `decouplerpy`). Still no broader multi-specialist /
direct-response routing bank (explicitly out of scope per
`eval/pilot_questions.json` metadata).
**Planned**: investigate the OOS-002 misroute; expand the bank beyond
DecoupleRpy-only scope once a second specialist exists.

### 2. No error handling for specialist timeout
If `anne-voigt/Paper2Agent_decoupleRpy` is sleeping (HF free tier), the gradio_client
call times out with no user-friendly message.
**Planned**: Add timeout handling with a "specialist is starting up, retry in ~30s" message.

Note: distinct from the step-limit issue fixed by `98c2a61` (2026-06-09) —
that fix handles the specialist *running* but hitting LangGraph's step cap;
this item is about the specialist *not yet awake* (cold start / HF free-tier
sleep).

### 3. Single specialist hardcoded
Only `decouplerpy` is wired. The `agents.yaml` registry exists but a second specialist
has never been added. When a second agent is ready, test the multi-agent routing path.

### 4. research_agent_token exposed in chat log
The HF write token was shared in plaintext in a prior session.
**ACTION REQUIRED**: Rotate at huggingface.co/settings/tokens.

### 5. Intelligent dataset selection — MEDIUM PRIORITY
The GUI dataset selector (added 2026-06-09) is user-driven only. There is no
guidance for the agent on *which* datasets to prefer when the user hasn't specified.
The live registry is already injected into the specialist's system prompt, so the
raw material is there. What's missing is explicit selection heuristics.

Examples of reasoning that should be encoded:
- "User asked about survival → prefer datasets with encoded survival endpoints
  (puleo_2018, paca_au_rnaseq, gse28735, gse50827_nones, gse57495, cptac_pda)"
- "User asked about normal vs. tumor → prefer matched-pair datasets (gse16515_mayo, gse28735_pdac)"
- "User wants robust findings → suggest running on multiple independent cohorts"
- "User asked about subtypes → filter to datasets with subtype labels (gse71729_moffitt, paca_au_rnaseq, puleo_2018)"

**Implementation plan:**
- Update `coordinator_system_prompt` or `routing_prompt` in `prompts.yaml` with
  dataset selection heuristics (one section per research question type)
- Optionally: add a lightweight `dataset_recommend` tool to the specialist that
  takes a research question and returns ranked suggestions with rationale
- The dataset_recommend tool path touches DecoupleRpy_Agent tool code, not just prompts

**Estimated effort:** 0.5–1 day. Mostly prompt engineering. The tool variant adds ~0.5 days
for tool implementation + testing. Low implementation risk; requires careful prompt testing
to avoid the agent ignoring the heuristics or over-constraining.

### 6. Conversation persistence ("saved state") — MEDIUM PRIORITY
Users have no way to save a conversation and return to ask follow-up questions.
Each session starts fresh — no history is preserved across browser refreshes or
HF Space restarts.

The coordinator currently holds conversation state in a Gradio `chatbot` component
(client-side only, lost on reload). The specialist has no memory of prior turns at all.

**Implementation options (in order of complexity):**
1. **Session export/import (lightweight):** Add a "Save conversation" button that
   serializes the chatbot history to JSON and offers download. A "Load conversation"
   file input restores it. No backend required. User manages files. ~0.5 day.
2. **Browser localStorage persistence (medium):** Use Gradio's JS injection to persist
   chatbot history to localStorage on every message. Auto-restores on page reload.
   Same session only — lost if user switches devices. ~1 day.
3. **Named sessions with server-side storage (full):** Add a session ID / name field.
   Store conversation history in a backend (HF dataset, simple SQLite, or KV store).
   User can name and return to sessions across devices. Requires a storage layer.
   ~2–3 days depending on storage choice. Most useful for recurring research workflows.

**Recommended approach:** Start with option 1 (export/import) to validate the use case,
then assess if full session storage is worth the backend complexity.

**Estimated effort:** Option 1 = ~0.5 day. Option 3 = ~2–3 days.
Key constraint: HF Spaces free tier has no persistent filesystem — option 3 needs
an external storage target (HF dataset repo as a JSON log, or a simple cloud KV).

Note: `83b837e6` (2026-06-09, currently the `hf/main` HEAD) already added
"session save/load to Gradio UI" — re-check whether this implements option 1
above (or a variant) before starting new work on this item.

---

## Git / Deployment State

| Remote | URL | Status |
|--------|-----|--------|
| `origin` | `github.com/avoigt1121/research-coordinator` | `main` @ `93056cf` |
| `hf` | `huggingface.co/spaces/anne-voigt/research_coordinator` | `main` @ `93056cf` |

`origin` is the source of truth. `.github/workflows/sync-to-hf-space.yml`
force-pushes `origin/main` → `hf` on every push to `main` — do not push
directly to `hf` (it will be overwritten on the next sync). `HF_TOKEN` repo
secret added 2026-06-13; first successful run not yet confirmed (run
27473037298 predates the secret and failed as expected).
