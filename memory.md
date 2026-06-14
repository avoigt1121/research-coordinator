# memory.md — Research Coordinator Working State

Last updated: 2026-06-13

---

## Current State

Deployed and functional. **`origin`, `hf`, and the live Space are all in sync
at `92095ea`** — confirmed `RUNNING` via the HF Space runtime API
(`sha: 92095ea064cf631a4e7a844a2d4e1a0df7dcedf4`). The
auto-continue-past-step-limit fix (`98c2a61`) and the rest of the
2026-06-09/06-12 eval-harness work are now live.

**This class of drift shouldn't recur**: `.github/workflows/sync-to-hf-space.yml`
(added 2026-06-12) force-pushes `origin/main` → `hf` on every push to `main`.
`origin` is now the source of truth — do not push directly to `hf`.

`HF_TOKEN` repo secret (write access to `anne-voigt/research_coordinator`)
was added 2026-06-13 and is **confirmed working**: run
[27474397877](https://github.com/avoigt1121/research-coordinator/actions/runs/27474397877)
(triggered by `92095ea`) succeeded end-to-end including the "Push to Hugging
Face Space" step, and the live Space rebuilt and is `RUNNING` at that sha.
No further action needed on this item.

---

## What Was Done (2026-06-13, this session)

- **Specialist cold-start handling** (Known Issue #2, resolved): added
  `ResearchRouter.specialist_status_note()` (`router.py`), which checks
  `https://huggingface.co/api/spaces/{hf_space}/runtime` and returns a
  "Space is currently `{stage}` — waking up can take ~30-60s" note when the
  Space isn't `RUNNING`. `gradio_ui.py` appends this to the routing message
  shown before dispatch. Also added `SPECIALIST_TIMEOUT_SECONDS = 120` and
  pass `httpx_kwargs={"timeout": 120}` to `GradioClient(...)` so a cold/dead
  Space fails with the existing friendly "could not be reached" message
  instead of hanging indefinitely. Added `httpx>=0.24` to `requirements.txt`.
- **Intelligent dataset selection** (Known Issue #5, implemented — pending
  eval verification): two-part change per
  `/Users/annivoigt/.claude/plans/radiant-fluttering-cerf.md`.
  - **DecoupleRpy_Agent** (`/Users/annivoigt/Documents/GitHub/DecoupleRpy_Agent`,
    uncommitted): `src/agent.py` now passes `survival_columns` through to the
    per-dataset prompt dict (both call sites in `get_system_prompt()` and
    `generate()`). `prompts.yaml` gains a new "## Dataset Selection
    Heuristics" section (survival/prognostic, tumor-vs-normal matched-pair,
    subtype (Bailey/Moffitt/Puleo), and no-preference/robust-cohort guidance,
    each naming specific `dataset_id`s) plus an updated Efficiency Rule #1
    telling the agent to apply it and state its choice + rationale before
    proceeding when no dataset is named.
  - **research-coordinator**: `routing_prompt` now returns a `dataset_status`
    field (`specified` / `no_preference` / `unspecified` / `meta`);
    `ResearchRouter.classify()` passes it through and a new
    `classify_dataset_reply()` checks whether a follow-up message answers a
    pending dataset prompt. `gradio_ui.py` adds a `pending_specialist`
    `gr.State`: on `dataset_status=="unspecified"` the coordinator asks the
    user to pick a dataset or say "no preference" instead of dispatching
    immediately; the next turn either combines the reply with the original
    request and dispatches, or (if it looks unrelated) discards the pending
    prompt and classifies fresh.
  - Verified via live API calls in `/tmp/rc_venv313`: all four
    `dataset_status` values classify correctly, and both
    `classify_dataset_reply()` paths ("no preference" → heuristics note,
    "use tcga_paad" → dataset-id note, unrelated question → `is_reply:
    False`) work as expected. DecoupleRpy_Agent side verified via a
    standalone Jinja render (not yet tested against the live agent — its
    repo has no local venv with `langchain_core` installed).
- **Eval rerun (Item 7), completed**: re-ran `eval/pilot_questions.json` (18
  questions) in a Python 3.13 venv (`/tmp/rc_venv313`, gradio_client 2.5.0) —
  see "Eval Environment Note" below. First attempt crashed at question 8/18
  (INF-016) with `anthropic.BadRequestError: ... credit balance is too low`
  (account-level, not a code issue — user topped up credits). Resumed via
  checkpoint (`eval/results/run_20260613_resume.log`), which skipped the 7
  already-completed questions and ran 8-18 to completion. Final results in
  `eval/results/20260613_195026_{raw,graded,report}.md`:
  - **Quality: 5 PASS / 6 PARTIAL / 7 FAIL** (2026-06-09 baseline: 8/2/8 —
    fewer outright fails but also fewer clean passes; net roughly flat to
    slightly worse).
  - **Routing: 17/18 correct** — OOS-002 (primer-design question) still
    misroutes to `direct` instead of `decouplerpy`, same as the 2026-06-09
    baseline. Pre-existing, not introduced by this session's changes.
  - **Latency: 181.1 min total, avg 603.5s/question** (min 18.3s, max
    2193.4s) — roughly double the 2026-06-09 baseline (101.8 min / 339.5s
    avg). The INF-007 2193s run is a genuine multi-step analysis (DESeq2
    survival split + PROGENy ULM) that completed with a full solution, not a
    hang — but the doubled avg latency overall is a UX consideration (no
    incremental feedback during long specialist runs).
  - **New finding — fabrication pattern**: the LLM judge repeatedly flagged
    ANS-001, ANS-005, ANS-009, INF-005, INF-007, INF-016, OOS-009, and
    OOS-013 as likely *fabricating* results — precise-looking numbers
    presented with no visible code/tool execution trace. Worth investigating
    whether the specialist is actually running its tools for these or
    narrating plausible-sounding output.
  - **New finding — context-bleed-looking responses**: LIM-017, NOD-003, and
    NOD-010 returned responses that look like replies to a *different,
    unrelated* turn (e.g. NOD-003 returned "No actionable user instruction
    has been received in this turn. I am ready and waiting."; NOD-010
    returned "You're welcome — standing by for your next request."; LIM-017
    returned "Acknowledged. No analysis requested, none performed."). These
    read like session-state bleed in the gradio_client dispatch across
    consecutive eval questions and warrant follow-up.
  - Dataset-selection-heuristics verification (the original motivation for
    this rerun) is inconclusive from this run alone — INF-005/007/016 are
    among the PARTIAL/fabrication-flagged results, so it's unclear whether
    the new heuristics are firing correctly in practice. Re-check once the
    context-bleed and fabrication issues are understood.
- Confirmed Known Issue #8-equivalent (docx claim that `_FALLBACK_DATASETS`
  in `gradio_ui.py` has only 15 entries) is incorrect — it has all 16,
  matching the current biodata-registry manifest set. No fix needed.

### Eval Environment Note
The local dev environment's default Python (3.9, via
`/Library/Developer/CommandLineTools/usr/bin/python3`) can only install
`gradio_client<=1.3.0`, which predates Gradio's `/gradio_api/` `api_prefix`
routing scheme (introduced in Gradio 5.x). Against the now-upgraded
DecoupleRpy Space (Python 3.11 / gradio 5.49.0), `gradio_client 1.3.0`'s
`_get_api_info()` hits `/info?serialize=False` (200, SPA HTML) instead of
`/gradio_api/info?serialize=False`, raising `JSONDecodeError: Expecting
value: line 1 column 1 (char 0)` for every specialist call. **For eval runs
against the live Space, use `/tmp/rc_venv313` (Python 3.13, gradio_client
2.5.0)** or otherwise ensure `gradio_client>=1.4.0` (requires Python>=3.10).

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

### 2. ~~No error handling for specialist timeout~~ — RESOLVED 2026-06-13
`ResearchRouter.specialist_status_note()` checks the HF Space runtime API and
surfaces a "Space is `{stage}` — waking up can take ~30-60s" note before
dispatch; `GradioClient` now has a 120s `httpx_kwargs` timeout so a cold/dead
Space falls through to the existing friendly error message instead of hanging
indefinitely. See "What Was Done (2026-06-13, this session)".

Note: distinct from the step-limit issue fixed by `98c2a61` (2026-06-09) —
that fix handles the specialist *running* but hitting LangGraph's step cap;
this item was about the specialist *not yet awake* (cold start / HF free-tier
sleep).

### 3. Single specialist hardcoded
Only `decouplerpy` is wired. The `agents.yaml` registry exists but a second specialist
has never been added. When a second agent is ready, test the multi-agent routing path.

### 4. research_agent_token exposed in chat log
The HF write token was shared in plaintext in a prior session.
**ACTION REQUIRED**: Rotate at huggingface.co/settings/tokens.

### 5. Intelligent dataset selection — IMPLEMENTED 2026-06-13, pending eval verification
Implemented per `/Users/annivoigt/.claude/plans/radiant-fluttering-cerf.md` —
see "What Was Done (2026-06-13, this session)" for the full description
(DecoupleRpy_Agent prompt heuristics + `survival_columns` passthrough;
research-coordinator `dataset_status` routing field + clarifying-prompt
flow). DecoupleRpy_Agent changes are uncommitted. Once both sides are
committed/deployed, re-run `eval/pilot_questions.json` and check the
INFER_DATASET-category questions (INF-005/007/016) for: (a) the specialist
stating its chosen `dataset_id` + rationale, and (b) `dataset_status` ==
`no_preference` for these (so the coordinator's clarifying prompt doesn't
fire for them).

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
