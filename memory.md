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
  - **New finding — "context-bleed" responses on LIM-017/NOD-003/NOD-010 —
    ROOT-CAUSED AND FIXED 2026-06-13** (same session, follow-up
    investigation): these weren't session bleed at all — `gradio_client`
    generates a fresh `session_hash`/`gr.State` per `Client()` instance, so
    sessions ARE isolated. The real bug was in
    `ResearchRouter.dispatch_to_specialist`'s auto-continue loop
    (`router.py`, the `98c2a61` "auto-continue past step limit" logic): when
    the Space's `chatbot_history` contains a "✅ Final Solution" block
    **followed by** a "⏸ Step limit reached" notice (the step that produced
    the solution also happened to be the limit-hitting step — common, since
    `interact_with_agent` always appends the notice when
    `step_limit_hit=True` regardless of whether a solution preceded it),
    `_extract_response` correctly returns both `solution` (set) and
    `step_limit_hit=True`. The old loop condition `if not step_limit_hit:
    break` ignored the already-found `solution` and called
    `/handle_continue` anyway — telling an agent that had *already finished*
    to keep going. The agent's "continuation" reply is a confused
    acknowledgement ("You're welcome — standing by for your next request.",
    "Acknowledged. No analysis requested, none performed.",
    "No actionable user instruction has been received in this turn..."),
    which (since it's *also* rendered with `solution-content` styling)
    overwrites the original good `solution` on the next loop iteration and
    becomes the final returned text.
    **Fix**: changed the loop condition to `if solution or not
    step_limit_hit: break` — if a Final Solution was already produced, don't
    call `/handle_continue` even if the step-limit notice also fired.
    Verified live: replayed NOD-003 ("Run decoupleR on the Chan-Seng-Yue PDAC
    dataset.") with the fix in place — now correctly returns a REFUSE_NO_DATA
    response (explains Chan-Seng-Yue isn't registered, lists the 16
    registered datasets, offers alternatives) instead of "No actionable user
    instruction...". This would grade PASS.
  - **REVISED finding — "fabrication" on ANS-001/005/009 (and likely
    INF-005/007/016, OOS-009/013) is a REAL agent bug, not just an eval
    trace-visibility gap.** A second live diagnostic replayed ANS-001 ("Run
    ULM with CollecTRI on tcga_paad...") end-to-end (112-message
    `chatbot_history`, 15 "Executing Code"/14 "Execution Result" steps,
    `_extract_response` → `solution=None, step_limit_hit=True`, i.e. it never
    produced a Final Solution and hit the step cap). The trace shows:
    - Steps 1-8: the agent's first call (`decoupler_load_and_filter_data(...)`)
      fails with `NameError`, so it spends 8 steps introspecting its own
      sandbox (`dir()`, `sys.path`, walking `/app/src/tools/`) and reads the
      source of `/app/src/tools/bulk_dataset_tools.py` and
      `/app/src/workflows/activity_scoring.py`, confirming
      `dataset_score_bulk_samples` / `dataset_compare_activity_by_group` /
      `decoupler_*_enrichment*` are *defined in the codebase* with full
      docstrings.
    - `dir()` / `globals()` in the sandbox only ever exposes:
      `['Path', 'create_directory', 'np', 'numpy', 'os', 'pd', 'scipy',
      'write_dataframe_to_csv', 'write_dataframe_to_tsv', 'write_text_file']`
      — none of the decoupleR analysis tools are bound as callables.
    - Steps 9-12: the agent works around this by writing its own scanpy code
      — downloads the real TCGA-PAAD h5ad, confirms shape `(183, 59427)`
      (this **183** matches the number in the original eval response, so
      that part is genuinely executed), normalizes to log-CPM, saves a CSV.
    - Steps 13-15: calls `dataset_score_bulk_samples(...)` directly (the
      documented tool) → `NameError: name 'dataset_score_bulk_samples' is
      not defined` again; step 14 re-confirms no scoring/activity/ULM/
      CollecTRI/decoupler names exist in builtins or globals; step 15 lists
      all callables (still just the generic I/O helpers) and the run hits
      the step limit with no solution.
    - **Conclusion**: the decoupleR activity-scoring/enrichment tool
      functions (`dataset_score_bulk_samples`,
      `dataset_compare_activity_by_group`, `decoupler_tf_enrichment_collectri`,
      `decoupler_pathway_enrichment_progeny`, `decoupler_hallmark_enrichment`,
      `decoupler_load_and_filter_data`) are **defined in
      `/app/src/tools/`/`/app/src/workflows/` but not actually registered/
      bound in the live CodeAgent's Python execution namespace** on
      `anne-voigt/Paper2Agent_decoupleRpy`. Any EXECUTE question that needs
      one of these (TF activity, pathway/hallmark scoring, group comparison)
      cannot be completed for real — only the generic file-I/O helpers and
      (separately, since these worked in the earlier NOD-010 diagnostic)
      dataset-listing/loading tools are reachable.
    - The "183 samples" detail in ANS-001's original Final Solution is real
      (genuinely loaded via scanpy), but the "771 TFs passing tmin=5",
      activity ranges, and top-20 TF table have **no corresponding successful
      tool call anywhere in the 112-message trace** — they were generated by
      the LLM after exhausting its step budget without ever calling
      `dataset_score_bulk_samples`. This is consistent with ANS-005's judge
      verdict ("fabricated detailed numerical results... without actually
      executing the analysis", FAIL) and ANS-009's PARTIAL.
    - **Severity**: this is a core-capability bug — TF activity / pathway
      scoring is the system's primary value proposition, and on the live
      Space it appears to silently fall back to plausible-sounding fabricated
      output rather than erroring visibly.
    - **Root-caused (follow-up, same session) to MCP tool-loading in
      `DecoupleRpy_Agent/gradio_ui.py`.** Traced the tool pipeline:
      `server.py` mounts 10 FastMCP sub-servers (incl.
      `bulk_dataset_mcp` → `dataset_score_bulk_samples`,
      `dataset_compare_activity_by_group`) with `mcp.mount(..., prefix=None)`
      — **confirmed locally** via a live stdio `list_tools()` call: all 47
      tools, including `dataset_score_bulk_samples` and
      `decoupler_load_and_filter_data`, are discovered under their exact
      unprefixed names (matches what the system prompt documents — naming is
      NOT the bug).
      `agent.execute()` (`src/agent.py:244`) calls
      `self.python_executor.send_functions(self.get_all_tool_functions())`
      before every step, and `get_all_tool_functions()` →
      `tool_manager.get_all_functions()` reads from `_tool_catalog`
      (`tool_manager.py:312-318`) — so *if* `_tool_catalog` contains the 47
      MCP tools, they'd be injected. The diagnostic's sandbox `dir()`/
      `globals()` showed **only** the 6 hardcoded fallback helpers from
      `PythonExecutor.reset()` (`python_executor.py:39-64`:
      `write_text_file`, `write_dataframe_to_csv`, `write_dataframe_to_tsv`,
      `create_directory`, plus `pd`/`np`/`os`/`Path`/`scipy`) — meaning
      `_tool_catalog` had **zero** MCP tools for that session.
      `_tool_catalog` is populated two ways in `gradio_ui.py`:
      1. **Pre-warm path** (`_prewarm_mcp()`, ~lines 138-158, background
         thread at app startup): spawns a seed `CodeAgent`, calls
         `seed.add_mcp(mcp_config_path)`, caches
         `seed.tool_manager.mcp_manager.mcp_functions` into
         `self._mcp_cache`. **Any exception is silently caught** (`except
         Exception as exc: print(...)`) leaving `self._mcp_cache = {}`.
      2. **Per-session restore/fallback** (`interact_with_agent()`, ~lines
         710-745): waits up to 180s
         (`self._mcp_ready.wait(timeout=180)`) for the pre-warm; if
         `self._mcp_cache` is non-empty, restores it into
         `mgr.mcp_manager.mcp_functions` and re-registers `_tool_catalog`.
         If empty, falls back to `session_state["agent"].add_mcp(...)`
         directly — **also wrapped in a silent `except Exception as e: print(f"⚠️
         Could not load MCP tools: {e}")`** that doesn't surface to the
         chat/agent or block the run.
      **Net effect**: if `add_mcp()` (which spawns the `server.py` MCP
      subprocess via stdio) fails or doesn't finish in either path on the
      live Space — plausible causes: HF Space container resource limits
      during cold start, the `rpy2`/R install warning seen in
      `server.py`'s own startup (`"R dependency installation failed, limma
      may be unavailable: rpy2 is not installed"`), or simply the 180s
      pre-warm timeout racing the `cache-preloader` background thread
      (`src/cache.py: preload_datasets`) for resources — the session
      proceeds with **zero MCP tools** and no visible error. The agent then
      behaves exactly as observed: tries documented tool names, gets
      `NameError`, explores the codebase to "rediscover" tools that were
      never injected, and after burning its step budget on real-but-useless
      exploration (writing real intermediate scanpy code), produces a
      plausible-but-fabricated "Final Solution".
      **Confirmed NOT the bug**: tool naming/mounting/prefixing (works
      correctly in a clean local `add_mcp()` call, ~10s, 47 tools).
      **Fix implemented (same session, `DecoupleRpy_Agent/gradio_ui.py`,
      uncommitted as of end of session)**: (1) `_prewarm_mcp()` and the
      `interact_with_agent()` fallback `add_mcp()` no longer swallow
      exceptions silently — both now `traceback.print_exc()` on failure, and
      `_prewarm_mcp()` logs an explicit warning if `add_mcp()` completes but
      discovers 0 MCP tools; (2) after the per-session tool
      cache-restore/fallback, `interact_with_agent()` now records
      `session_state["mcp_tool_count"]` via
      `agent.get_tool_statistics()["by_source"]["mcp"]`, and if it's 0, the
      very next thing the chat does is yield a red "Analysis tools
      unavailable" notice and `return` — refusing the request instead of
      letting the LLM explore/fabricate; (3) added
      `_mcp_health_markdown()` + `demo.load(...)` wiring a status line
      (`mcp_status = gr.Markdown(...)`) near the top of the UI, showing
      either "decoupleR analysis tools: 47 loaded ✓" or a red "Analysis
      tools failed to load (0 ... )" banner — observable without a live
      diagnostic replay.
      **Self-test note — CORRECTED 2026-06-14, see "What Was Done
      (2026-06-13/14)" below.** The original note (this session) concluded
      the `python`/`python3` PATH issue was "a test-harness artifact, not a
      live-Space bug" and that no `mcp_config.yaml`/code change was needed.
      **This was wrong.** `mcp_config.yaml`'s `command: ["python3",
      "server.py"]` is resolved via `PATH` *at MCP-subprocess-spawn time* by
      `mcp_manager.py`'s `add_mcp_server`, which is a different resolution
      than "whatever launched `gradio_ui.py`/`app.py`" — on a fresh HF Space
      build, `python3` on `PATH` can land on a system interpreter without
      this project's `requirements.txt` installed, so the MCP subprocess
      dies with `ModuleNotFoundError: No module named 'fastmcp'` and the
      handshake silently returns 0 tools. Confirmed live: this WAS production's
      actual failure mode. Fixed by mapping `cmd in ("python","python3")` →
      `sys.executable` in `add_mcp_server` (commit `7b766b1`) — confirmed
      deployed and the subprocess now starts with the correct interpreter/deps.
      0-tools persisted after this fix for a separate, still-unresolved reason
      (see Known Issue #7 below).
    - **Hypothesis checked and closed**: the `/lambda_2` +
      `/interact_with_agent_1` pair is NOT a separately configured
      agent/toolset. `gradio_ui.py` (~lines 1073-1091) wires the *same*
      `self.interact_with_agent` method (with the same
      `[stored_messages, chatbot, session_state]` args and the same shared
      `self._mcp_cache`/`_prewarm_mcp`) to two UI events —
      `text_input.submit(...)` (Enter key) and `submit_btn.click(...)`
      (Submit button) — each preceded by an identical `lambda x: (x, "",
      ...)` step. Gradio auto-suffixes duplicate function bindings (`_1`),
      producing `/lambda`+`/interact_with_agent` and
      `/lambda_2`+`/interact_with_agent_1`. Both paths share the exact same
      MCP-loading code and are equally exposed to the silent-failure bug
      above — there's no "other wiring" to fix separately.
    - The earlier "trace-visibility / judge can't verify" framing (below,
      now superseded) is still *true as a secondary issue* — even successful
      tool calls are stripped from what the judge sees — but it is not the
      primary explanation for these PARTIAL/FAIL verdicts. The
      tool-execution-trace digest idea is still worth doing for general
      transparency, but won't turn ANS-001/005/009 into PASSes by itself;
      fixing the tool-binding bug is the prerequisite.
  - **Dataset-selection-heuristics (Known Issue #5) — VERIFIED WORKING**:
    re-reading the raw responses, all three INFER_DATASET questions now state
    a chosen `dataset_id` + rationale before proceeding, per the new prompt
    section: INF-005/INF-007 pick `tcga_paad` ("largest curated... Knudsen
    curation"), INF-016 picks `gse71729_moffitt` ("largest single available
    cohort (n=357 samples)... most statistically robust"). The judge confirms
    "satisfying the INFER_DATASET requirement" for all three — the only thing
    holding them at PARTIAL is the shared fabrication/trace-visibility issue
    above, not the dataset choice. No further action needed on Known Issue #5
    beyond the trace-digest follow-up.
  - **New finding — OOS-002/009/013 (REFUSE_OUT_OF_SCOPE, all 3 FAIL) share a
    second root cause: no system has "out of scope" awareness.**
    - **OOS-009** ("Fit a Kaplan-Meier curve and report the log-rank
      p-value...") and **OOS-013** ("Deconvolve bulk tumor samples into
      cell-type fractions") route correctly to `decouplerpy`
      (`routing_correct: true`), but `DecoupleRpy_Agent`'s `prompts.yaml` has
      no general "capabilities/out-of-scope" section — only *per-dataset*
      `refusal_rules`. decoupleR doesn't do survival statistics (KM curves,
      log-rank, Cox models) or cell-type deconvolution (CIBERSORTx/BisqueRNA
      territory); with no guidance saying so, the agent attempts a
      workaround and produces an elaborate "results" narrative the judge
      flags as fabricated. **Proposed fix**: add a "## Capabilities &
      Out-of-Scope" section to `DecoupleRpy_Agent/prompts.yaml` listing
      analysis types decoupleR doesn't perform (survival stats, cell-type
      deconvolution, anything requiring a different statistical
      framework), noting decoupleR *activity scores* can feed into such
      downstream tools but the agent itself shouldn't compute/fabricate
      them, and instructing the agent to state the limitation + suggest the
      appropriate external tool (lifelines/survival for KM, CIBERSORTx/
      BisqueRNA for deconvolution) instead of attempting a substitute
      analysis.
    - **OOS-002** ("Design qPCR primers for KRAS") is a different case —
      it's not a bioinformatics-analysis question at all (wet-lab protocol
      design), and `routing_correct: false` (misroutes to `direct`).
      research-coordinator's `routing_prompt` has no "out of scope" category
      — "Design qPCR primers for KRAS" matches "Conceptual question about
      biology, genes, pathways" (mentions a gene) and routes `direct`; the
      `coordinator_system_prompt` then says the coordinator has "deep
      knowledge of gene biology" with no scope boundary, so Claude happily
      designs primers. **Proposed fix**: add an "out of scope" category to
      `prompts.yaml`'s `routing_prompt` (wet-lab/protocol questions
      unrelated to PDAC transcriptomics analysis) and a corresponding
      instruction in `coordinator_system_prompt` to decline such questions
      directly, explaining the system's scope (PDAC decoupleR-based
      transcriptomic analysis) rather than answering from general knowledge.
    - Neither fix implemented yet this session — both are prompt-only
      changes, low risk, good candidates for the next session.
  - **ANS-021** ("...using a ranked logFC list I provide", PARTIAL) is a
    likely eval *question-design* issue, not an agent bug: the agent
    correctly sets up GSEA infrastructure, loads TCGA-PAAD, and asks the user
    to paste their ranked logFC list — but `run_eval.py` is single-turn, so
    no list is ever provided and the agent can't proceed to EXECUTE. Either
    rephrase ANS-021 to include inline data, or accept "asks for required
    input" as a valid outcome for this question.
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

## What Was Done (2026-06-14, this session — "Go on with group 1 issue")

Direct continuation of the prior session's Group 1 investigation (below).
**Group 1 is now RESOLVED** — see Known Issue #7 (renumbered/struck-through)
for full root cause, fix commits (`eee2782`, `5e4fed7` in `DecoupleRpy_Agent`),
and confirmation evidence (47 MCP tools loaded + a real end-to-end analysis
run with genuine tool calls and a saved HF run log).

Groups 3/4/5 (presented as a plan in the prior session) remain
not-yet-implemented, awaiting explicit user go-ahead. Suggested next step:
a clean re-run of `eval/pilot_questions.json` to check whether
ANS-001/005/009 now PASS with real tool-call traces (previously FAIL/PARTIAL
due to fabrication under the 0-MCP-tools bug).

---

## What Was Done (2026-06-13/14, this session — fully autonomous, 0 new user messages)

Continuation of standing instructions from 2026-06-13 ("fix Group 2, then
build/execute a plan for Groups 3/4/5"). Groups 3/4/5 (prompt-only changes in
`DecoupleRpy_Agent`/`research-coordinator`) can't be properly verified while
the specialist has 0 MCP tools, so this session focused on Group 1
(root-causing the 0-MCP-tools bug, Known Issue #7 below in DecoupleRpy_Agent).

- **Group 2 — DONE.** `research-coordinator` `c5dbd4f`: `dispatch_to_specialist`
  retries the `/lambda` + `/interact_with_agent` dispatch with a fresh
  `gradio_client` session (up to `MAX_DISPATCH_RETRIES=2`) if the agent's
  reply doesn't echo back the dispatched query — guards the intermittent
  `gr.State` race between the two calls.
- **Group 1 — PARTIAL, real progress, not fully resolved.** All changes in
  `DecoupleRpy_Agent` (origin IS the live HF Space — each push deploys):
  - `7b766b1` — **root-cause fix**: `mcp_manager.py`'s `add_mcp_server` now
    remaps `cmd in ("python","python3")` → `sys.executable` before spawning
    the MCP subprocess (PATH-resolved `python3` could land on a system
    interpreter without this project's deps — see corrected Self-test note
    above). Also added a raw subprocess startup probe to `_prewarm_mcp()`
    (`gradio_ui.py`) that runs `sys.executable server.py` directly and
    records its rc/stdout/stderr tail into `_mcp_discovery_errors["_raw_startup"]`,
    independent of the MCP handshake. **Confirmed deployed and working**: the
    probe shows `rc=0` with "Starting MCP server 'Paper2Agent' with transport
    'stdio'" and correct fastmcp/mcp versions — the subprocess itself now
    starts correctly in production, a real improvement over the prior
    `ModuleNotFoundError` state.
  - **Version-mismatch hypothesis investigated and ruled out**: production's
    unpinned `fastmcp`/`mcp` resolve to `fastmcp==2.11.2`/`mcp==1.10.1` on a
    fresh build (vs. local `.venv`'s `fastmcp==3.2.3`/`mcp==1.27.0`). Tested
    both combinations locally with the `sys.executable` fix — **both produce
    47 tools**. Version mismatch is not the cause of 0 tools.
  - `04d1576` (reverted) — attempted to pin `fastmcp>=3.2.3`/`mcp>=1.27.0` in
    `requirements.txt` to match the locally-verified-working combo. Caused
    `BUILD_ERROR` in production: `gradio[oauth,mcp]==5.49.0` (hardcoded into
    HF's build process, not from `requirements.txt`) hard-pins `mcp==1.10.1`
    — direct conflict, confirmed via `info.runtime.raw['errorMessage']` and a
    local `pip install --dry-run`.
  - `bc579fd` — `git revert --no-edit 04d1576`, pushed immediately. Confirmed
    Space back to `RUNNING` at `bc579fd`. **Net `requirements.txt` change for
    the session: zero** — `fastmcp`/`mcp` remain unpinned.
  - `969a577` — round-5 diagnostic: `discover_mcp_tools_sync` now wraps
    `session.initialize()` and `session.list_tools()` in
    `asyncio.wait_for(..., timeout=60)` with per-step timing recorded in a
    `timing` dict, and **always** populates
    `last_discovery_errors[server_name]` (either with `"handshake timing:
    {...}"` if `discovered_tools` is empty, or with the
    exception+timing on error) — closing the previous gap where 0 tools could
    occur with no diagnostic info at all.
  - **Result after `969a577`, deployed and checked via `_mcp_health_markdown`**:
    still 0 MCP tools, but `_mcp_discovery_errors` contains **only**
    `_raw_startup` (subprocess starts fine, correct interpreter/versions) —
    **no `decouplerpy` key at all**. Per the new code this should be
    impossible if `discovered_tools` ends up empty (one of the two branches
    above always sets it). Its absence implies `discovered_tools` is
    *non-empty* inside `_discover_async`, yet `self._mcp_cache` /
    `mcp_functions` end up empty by the time `_mcp_health_markdown` reads
    them. **This is the new, narrower mystery — see Known Issue #7.**
  - Per self-imposed instruction, `969a577` is the last diagnostic round for
    now — stopping further DecoupleRpy_Agent deploys pending the user's
    review of the Groups 3/4/5 plan (presented separately, see chat).
  - 403 Forbidden on `HfApi().fetch_space_logs()` remains unresolved — all
    diagnosis continues via code-level `/_mcp_health_markdown` instrumentation.
  - Commits this session, in order: (research-coordinator) `c5dbd4f`;
    (DecoupleRpy_Agent) `3a22ae7`, `e4428e8`, `457352f` (earlier in session,
    the silent-exception/health-markdown fixes referenced above),
    `7b766b1`, `04d1576` (reverted), `bc579fd` (revert), `969a577`.

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

### 7. ~~DecoupleRpy_Agent: 0 MCP tools loaded in production~~ — RESOLVED 2026-06-14
**(This was "Group 1" — the prerequisite for verifying Groups 3/4/5.)**

**Root cause** (the "no `decouplerpy` key, only `_raw_startup`" mystery from
the prior round-5 diagnostic): `tool_manager.py`'s `add_mcp_server()` wraps
`MCPManager.add_mcp()` in a generic `except Exception as e: print(...)` that
silently swallows exceptions to stdout — invisible because
`HfApi().fetch_space_logs()` 403s. `discover_mcp_tools_sync()` itself was
succeeding (hence no `last_discovery_errors['decouplerpy']`), but
`add_mcp()`'s **module-level import** of `from langchain_mcp_adapters.tools
import _list_all_tools` (mcp_manager.py line 162) was raising `ImportError:
cannot import name 'streamable_http_client' from
'mcp.client.streamable_http'` — caught by `add_mcp_server`'s silent except,
*before* any per-server discovery even ran.

The actual incompatibility: unpinned `langchain-mcp-adapters` resolves to
`0.3.0`, which imports the renamed `streamable_http_client` symbol — present
only in `mcp>=~1.12`. But `gradio[oauth,mcp]==5.49.0` (hardcoded into HF's
build process, not in `requirements.txt`) hard-pins `mcp==1.10.1`, which only
has the old name `streamablehttp_client`. Both `langchain-mcp-adapters`
versions declare `mcp>=1.9.2` in their metadata, so pip's solver never flags
a conflict — it's a runtime-only symbol-rename incompatibility.

**Fix** (`DecoupleRpy_Agent`):
- `eee2782` — diagnostic: `add_mcp_server`'s except clause now records
  `type(e).__name__`, the message, `mcp_functions` count at failure, and a
  traceback into `last_discovery_errors["_add_mcp_server"]`. Zero behavior
  change on the success path; immediately surfaced the `ImportError` above
  via `/_mcp_health_markdown` once deployed.
- `5e4fed7` — **the fix**: pin `langchain-mcp-adapters<=0.2.2` in
  `requirements.txt` (0.2.2 still imports the old `streamablehttp_client`
  name, present in both `mcp==1.10.1` and newer `mcp` releases). Local
  `.venv` was already at `0.2.2` — which is why all prior local tests showed
  47 tools while production showed 0; the bug only manifested with prod's
  dependency resolution.

**Confirmed live** (commit `5e4fed7`, `RUNNING`):
- `/_mcp_health_markdown` → `_decoupleR analysis tools: 47 loaded ✓_`.
- Manual `gradio_client` (`/tmp/rc_venv313`, `gradio_client==2.5.0`) replay of
  `/lambda` + `/interact_with_agent` with "Run decoupleR on the Chan-Seng-Yue
  PDAC dataset." produced a **real** multi-step run: `dataset_list_available()`
  executed for real (16 datasets returned), correctly concluded
  Chan-Seng-Yue isn't registered, and saved a real run log to
  `anne-voigt/decoupleRpy_results` on HF — i.e. genuine tool execution, not
  fabrication.

**Residual oddity (not blocking)**: a second attempt via
`/tmp/test_router_fix.py` (same two `gradio_client` calls, via
`ResearchRouter.dispatch_to_specialist`) ran for ~29 minutes with no result
and was killed; an earlier attempt via the stale system `/usr/bin/python3`
(`gradio_client==1.3.0`, see the `gradio_client<=1.3.0` note above) failed
instantly with the unrelated `JSONDecodeError` client-version issue. Since
the manual replay with the *same* two calls and the *same* venv succeeded
end-to-end, this is likely queue contention from running several concurrent
sessions against the Space during this debugging session, not a regression.
Worth a clean isolated retry of `eval/pilot_questions.json` (ANS-001/005/009)
to confirm real tool-call traces now appear — that re-run is the next
step, not yet done.

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
