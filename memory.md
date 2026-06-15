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
      (`routing_correct: true`), but `DecoupleRpy_Agent`'s `prompts.yaml` had
      no general "capabilities/out-of-scope" section — only *per-dataset*
      `refusal_rules`. decoupleR doesn't do survival statistics (KM curves,
      log-rank, Cox models) or cell-type deconvolution (CIBERSORTx/BisqueRNA
      territory); with no guidance saying so, the agent attempted a
      workaround and produced an elaborate "results" narrative the judge
      flagged as fabricated.

      **Group 3 — DONE 2026-06-14** (`DecoupleRpy_Agent` `b9efd4b`, deployed
      and confirmed `RUNNING` with 47 MCP tools still loaded): added a "##
      Capabilities & Out-of-Scope Analyses" section to `prompts.yaml`'s
      `system_prompt`, placed right after "## Handling Dataset Limitations
      and Refusals" and before "## Efficiency Rules". It lists survival
      statistics (KM/log-rank/Cox — no `lifelines`/R `survival` available)
      and cell-type deconvolution (CIBERSORTx/BisqueRNA/EPIC — decoupleR
      estimates activity, not composition) as out-of-scope, plus a catch-all
      for other non-decoupleR statistical frameworks (variant calling, GWAS,
      mutation signatures, primer/probe design). Instructs the agent to: not
      attempt a workaround, state the limitation, offer decoupleR
      activity/survival columns as *inputs* to the requested downstream tool
      where applicable, name the appropriate external tool, and stop in
      `<solution>`. Verified the rendered `get_system_prompt()` output
      (`.venv`, 51906 chars total) includes the new section correctly and
      Jinja parses cleanly.

      **Re-confirmed 2026-06-14** (post Group-4 deploy): HF Space
      `anne-voigt/Paper2Agent_decoupleRpy` still at sha `b9efd4b`, stage
      `RUNNING`; `/_mcp_health_markdown` reports "47 loaded ✓" — prompt-only
      change remains stable.

      **Not yet verified against eval**: re-run OOS-009/OOS-013 (and ideally
      the full `eval/pilot_questions.json`) to confirm they now produce a
      REFUSE_OUT_OF_SCOPE response instead of a fabricated result.
    - **OOS-002** ("Design qPCR primers for KRAS") is a different case —
      it's not a bioinformatics-analysis question at all (wet-lab protocol
      design), and `routing_correct: false` (misroutes to `direct`).
      research-coordinator's `routing_prompt` had no "out of scope" category
      — "Design qPCR primers for KRAS" matched "Conceptual question about
      biology, genes, pathways" (mentions a gene) and routed `direct`; the
      `coordinator_system_prompt` then said the coordinator has "deep
      knowledge of gene biology" with no scope boundary, so Claude happily
      designed primers.

      **Group 4 — DONE 2026-06-14** (`research-coordinator` `a3010ac`,
      synced to HF Space `anne-voigt/research_coordinator` via the
      `sync-to-hf-space.yml` workflow — run completed `success`, Space sha
      `a3010ac...`): added `"route": "out_of_scope"` to `routing_prompt`'s
      JSON schema with explicit criteria for wet-lab/protocol-design
      requests (primer/probe design, qPCR, cloning, plasmid construction,
      antibody/reagent selection, CRISPR guide design), noting this applies
      "even if the question mentions a gene or pathway relevant to PDAC".
      Added a new "## Scope" section to `coordinator_system_prompt` stating
      the system's scope (PDAC decoupleR transcriptomic analysis over the
      dataset registry) and instructing the coordinator to decline wet-lab
      questions, explain the scope boundary, and suggest external resources
      (PrimerBank, Primer-BLAST, lab core facility) instead of answering
      from general knowledge. Because `route` values other than
      `"specialist"` already fall through to `direct_response()` (which uses
      `coordinator_system_prompt`), no changes to `router.py` or
      `gradio_ui.py` were needed — the new route value is for
      classification/logging clarity, and the actual decline behavior comes
      entirely from the `## Scope` system-prompt addition.

      **Verified locally** (via `ResearchRouter` with `.env` loaded):
      - `classify("Design qPCR primers for KRAS")` →
        `{"route": "out_of_scope", "agent_id": null, "dataset_status": null,
        "reasoning": "Designing qPCR primers is a wet-lab/bench-work task,
        not a transcriptomic data analysis request."}`
      - `classify("Design CRISPR guide RNAs to knock out SMAD4")` and
        `classify("How do I clone KRAS into a plasmid for overexpression?")`
        both also correctly return `"out_of_scope"`.
      - `classify("What pathways does TP53 regulate?")` still returns
        `"direct"` (no over-triggering on conceptual gene questions).
      - `classify("Run a TF activity analysis, no dataset preference, on a
        large cohort")` still returns `"specialist"` /
        `"no_preference"` (no regression to Group 1/2 dataset-status
        routing).
      - `direct_response("Design qPCR primers for KRAS", [])` now declines,
        states the system's PDAC-decoupleR scope, points to PrimerBank/
        Primer-BLAST/a lab core facility for primer design, and offers the
        transcriptomic alternative (KRAS expression / MAPK pathway activity
        in registered PDAC datasets) instead of fabricating a primer
        sequence.

      **Not yet verified against eval**: re-run OOS-002 (and ideally the
      full `eval/pilot_questions.json`) to confirm it now produces
      `routing_correct: true` and a REFUSE_OUT_OF_SCOPE-style response.

      HF Space confirmed `RUNNING` at sha `a3010ac` post-deploy.
  - **ANS-021** ("...using a ranked logFC list I provide", PARTIAL) is an
    eval *question-design* issue, not an agent bug: the agent correctly sets
    up GSEA infrastructure, loads TCGA-PAAD, and asks the user to paste their
    ranked logFC list — but `run_eval.py` is single-turn, so no list is ever
    provided and the agent can't proceed to EXECUTE.

    **Group 5 — DONE 2026-06-14** (`research-coordinator` `b469629`): added a
    new `REQUEST_REQUIRED_INPUT` rubric category to `eval/run_eval.py`'s
    `JUDGE_RUBRIC` — PASS = agent does all the setup it can and then clearly
    asks for the missing user-supplied input without fabricating numbers;
    FAIL = fabricating results to avoid asking. Reclassified ANS-021's
    `expected_behavior` from `EXECUTE` to `REQUEST_REQUIRED_INPUT` in
    `eval/pilot_questions.json` with updated grading notes explaining the
    single-turn limitation. Re-graded the existing 2026-06-13 agent response
    against the new rubric with **no change to agent behavior**: judge
    verdict flipped from PARTIAL to PASS ("correctly identifies that the
    ranked logFC list is missing and asks for it in multiple usable formats
    ... without fabricating any GSEA results"). Not yet re-run as part of a
    full eval pass.
- Confirmed Known Issue #8-equivalent (docx claim that `_FALLBACK_DATASETS`
  in `gradio_ui.py` has only 15 entries) is incorrect — it has all 16,
  matching the current biodata-registry manifest set. No fix needed.

### Full 18-question eval re-run — 2026-06-14 (post Groups 1/3/4/5)

`eval/results/20260614_164236_{raw,graded,report}.json/.md` — live run against
both Spaces (`research-coordinator` `ec0448c`, `DecoupleRpy_Agent` `b9efd4b`,
both `RUNNING`). **Overall: PASS 12, PARTIAL 2, FAIL 4** (up from PASS 5,
PARTIAL 6, FAIL 7 on 2026-06-13), routing 17/18 "correct" by the harness's
automated check.

**Targeted fixes confirmed working:**
- **OOS-002** ("Design qPCR primers for KRAS"): FAIL → **PASS**. Now routes
  `out_of_scope` (Group 4) and the coordinator declines, states system scope,
  points to PrimerBank/Primer-BLAST, and offers the KRAS-pathway-activity
  alternative — judge: "exactly meeting the REFUSE_OUT_OF_SCOPE expectation."
  (The harness's automated routing-correctness check still flags this as a
  "routing failure" because `EXPECTED_AGENT_ID="decouplerpy"` for the whole
  bank — this is a harness limitation for this one question, not a real
  problem; the `out_of_scope` route is correct and desired.)
- **OOS-009** (Kaplan-Meier/log-rank) and **OOS-013** (cell-type
  deconvolution): both FAIL → **PASS**. Group 3's "## Capabilities &
  Out-of-Scope Analyses" section works live — both responses correctly state
  the limitation, name external tools (lifelines/R survival;
  CIBERSORTx/EPIC/BisqueRNA), and offer decoupleR outputs as inputs to those
  tools.
- **ANS-021**: PARTIAL → still **PARTIAL**, but for a *different* reason than
  before — judge confirms it now satisfies "REQUEST_REQUIRED_INPUT" (asks for
  the ranked list in a usable format, no fabricated GSEA numbers), but this
  run's response skipped the "do all the setup you can" half (didn't load
  tcga_paad / confirm Hallmark sets first, instead argued GSEA is out of
  decoupleR's scope). Group 5's rubric/category change is working as
  intended; this is now an agent-response variance issue, not an eval-design
  issue.
- **INF-007**: PARTIAL → **PASS** (Group 1's dataset-selection heuristics:
  picks TCGA-PAAD, justifies it, computes PROGENy activities, correctly
  notes survival stats are downstream/out-of-scope).

**New/recurring finding — widespread result fabrication (regressions vs
2026-06-13, likely agent-response variance not a prompt regression):**
**ANS-005** (FAIL, unchanged), **ANS-009** (PARTIAL → FAIL), **INF-005**
(PARTIAL → FAIL), **INF-016** (PARTIAL → FAIL), and **LIM-008** (PASS →
PARTIAL) all show the same pattern: the agent presents detailed,
precise-looking numeric results (Cohen's d, padj, specific TF rankings,
"83.8% of CollecTRI network genes matched", etc.) with no visible evidence of
actual tool execution. INF-005 additionally picked `paca_au_rnaseq` instead
of the expected `tcga_paad` ("largest curated RNA-seq cohort") and fabricated
results for that wrong dataset too. This is the same fabrication pattern
flagged earlier for INF-005/007/016 (see "shared fabrication/trace-visibility
issue" above) — it appears to be non-deterministic (these specific questions
PASS/PARTIAL on some runs, FAIL on others) rather than caused by the Group
3/4/5 prompt edits, since Groups 3/4/5 touched out-of-scope handling and
routing, not the EXECUTE code path. **Candidate "Group 6"**: investigate
whether `<solution>` is being reached without a preceding successful tool
call (trace visibility), and/or add an explicit system-prompt instruction
that numeric results in the final solution MUST come from an actual
`decoupler`/MCP tool call in this turn's trace — not yet implemented.

### Group 6 — fabrication deep-dive — DONE 2026-06-14

Deep-dived the "fabrication" FAILs (ANS-005/009, INF-005/016, LIM-008). Ran a
live diagnostic dispatch capturing the FULL chatbot_history (111 msgs, ~50
steps, 12 real tool-observation steps; `/tmp/diag_trace_full.json`) and checked
the solution's numbers against the actual tool outputs.

**Finding: the agent is NOT fabricating headline results.** Every headline
number traced to a real `dataset_compare_activity_by_group` observation —
`n_significant_05: 221`, `n_activities: 592`, the pairwise table (122/9/3/1/1),
and primary-contrast per-TF stats (obs msg 94:
`SNAI1 effect_size=2.151083, mean_test=2.191278, mean_control=0.360171` →
solution "SNAI1 +2.15, 2.19 vs 0.36"). Two real causes:
1. **Eval measurement artifact (dominant).** The coordinator's
   `_extract_response` returns only the Final Solution and discards the
   `<observation>` steps, so the judge saw a polished narrative with no visible
   computation and (told to grade strictly) inferred fabrication. False
   positive. Users see the same stripped view, so results weren't verifiable
   either.
2. **Memory-window confabulation (minor).** `memory_window=15` over a ~50-step
   run pushes early observation tables out of context; a minority of SECONDARY
   numbers were reconstructed from memory with small drift (PAX5 mean 2.04 vs
   real ~2.0x; FOXA1 1.64 vs 1.63; SNAI2 -2.23 vs -2.2).

**Fixes (eval + agent; chosen by user, honoring the memory_window constraint —
the trace is captured OUTSIDE the LLM context, no token/latency cost):**
- **Eval** (`research-coordinator` `3c04a2f`): added
  `ResearchRouter._extract_execution_trace()` (distills real "Code Output"
  observations + tool calls from the history the Space already returns) exposed
  via `dispatch_to_specialist(..., return_trace=True)`. `run_eval.py` captures
  it and feeds it to the judge; `JUDGE_RUBRIC` now grades fabrication against
  the TRACE, not narrative style. Verified on the captured trace: same solution
  → PASS with trace present, FAIL with trace empty (negative control).
- **Agent** (`DecoupleRpy_Agent` `d12ffc3`): added a mandatory "## Reporting
  Results: Provenance and Anti-Fabrication" section — every number in
  `<solution>` must come from a this-turn observation; re-read the saved
  results CSV in a final `<execute>` right before reporting (instead of
  reconstructing from scrolled-out memory) and quote it verbatim; cite tools
  run + output artifact paths; state plainly when a computation failed. Also
  marked Example 6's inline numbers as illustrative-only so they aren't
  pattern-copied. Renders cleanly; deploy confirmation pending below.

Full detail in structured memory `group6-fabrication-is-mostly-eval-artifact`.
Not touched: `memory_window` (the quadratic-cost guard) and temperature 0.7
(left as-is since headline numbers were real).

**DEPLOY + VERIFY (confirmed 2026-06-14):** agent `d12ffc3` deployed, Space
`RUNNING`, 47 MCP tools intact. Verification dispatch ("PROGENy ULM on
tcga_paad, top pathways by effect size") captured full trace
(`/tmp/diag_trace_full.json`, 60 msgs). New behavior confirmed working:
(1) the agent ran a final `pd.read_csv(.../tcga_paad_progeny_ulm_activities.csv)`
RE-READ step (msgs 41/49/52) immediately before the solution (msg 56);
(2) the `<solution>` cites provenance — "**Artifacts:**
`/app/tmp/outputs/tcga_paad_progeny_ulm_activities.csv`, `..._pvalues.csv`",
the tool `dataset_score_bulk_samples`, and method PROGENy ULM;
(3) every number in the 14-pathway results table traces EXACTLY to the re-read
observation (msg 52), with correct rounding (e.g. trace JAK-STAT 19.9758 →
solution 19.98; VEGF 14.3580 → 14.36; TGFb/p53/EGFR/Estrogen/PI3K all exact).
No confabulation. The eval judge would now also see this trace and grade it
PASS on evidence. Full eval re-run with both fixes not yet done (optional
follow-up).

### Fresh 10-question blind-spot eval — 2026-06-14

Ran a NEW stratified 10 (`eval/pilot_fresh10.json`, IDs disjoint from the
18-pilot) to avoid validating fixes only against questions seen during dev.
`eval/results/20260614_180906_*`. **PASS 7 / FAIL 3.** Session fixes held on
unseen questions: INF-015 → `paca_ca_rnaseq` (largest RNA-seq) and INF-019 →
`paca_au_rnaseq` (subtypes requested) BOTH correct → cohort-size heuristic
works; ANS-002 PASS with provenance CSV path; the fabrication backstop did not
false-fire on any refusal. The 3 FAILs were NEW blind spots, all the same
family ("requested X not exactly available"), none the Group 6 issue:
- **NOD-001** (REFUSE_NO_DATA): asked for LUAD; agent fetched REAL external
  TCGA-LUAD (576 samples = real LUAD size) via arbitrary Python and analyzed
  it. Not fabrication — a scope breach. **Product decision (Anne): this is
  DESIRED, just needs a 'not curated/validated' disclaimer.** See structured
  memory [[blindspot-agent-fetches-external-non-registered-data]].
- **LIM-006** (FLAG_LIMITATION): asked for protein-level from cptac_pda (only
  RNA-seq TPM registered); agent silently ran RNA-seq and labeled it
  "Protein-level" → under-sensitive.
- **ANS-013** (EXECUTE): asked for AUCell (not exposed); agent refused + asked
  permission instead of substituting ulm/mlm and running → over-sensitive.

**Fix — Availability & Substitution Policy** (`DecoupleRpy_Agent` `f39da02`,
deployed): one prompt section keyed on whether a substitute changes the MEANING
of the answer. (1) method unavailable but supported method answers same
question → substitute + RUN + note (fixes ANS-013); (2) only different-meaning
data available (protein→RNA) → flag as headline, never relabel (fixes LIM-006);
(3) cohort not in ## Available Datasets → may proceed but must prominently flag
"outside curated PDAC registry, not validated" (implements NOD-001 decision).
**Eval rubric updated** (`research-coordinator` `52b269c`): REFUSE_NO_DATA now
PASSes either a clean refusal OR proceed-with-prominent-disclaimer; FAILs only
if non-registered results are presented as curated or fabricated; different
assay/modality (ATAC/methylation/spatial) still expected to refuse. Not yet
re-run against the fresh 10 to confirm the 3 flip.

### Group 6 follow-ups — 2026-06-14

**INF-005 was NOT an eval-grading bug (correction).** Initially suspected the
grading note was wrong, but that was based on a conflated question wording
(the Bailey-subtype framing came from the *diagnostic* dispatch, not INF-005).
INF-005 actually asks "Estimate TF activities on the largest curated PDAC
RNA-seq cohort" — no subtypes. `tcga_paad` is the only RNA-seq cohort with a
curated subset (`curated_n=150`; manifests have NO `n_samples` field at all),
so the grading note (tcga_paad) is correct and the agent's pick of the
92-sample `paca_au_rnaseq` (rationalized with an unrequested Bailey qualifier)
was the weak answer. Grading left unchanged.

**Root cause of the bad pick: the agent had no size data.** Manifests carry no
`n_samples` field, so the agent literally could not rank cohorts by size.
**Fix (`DecoupleRpy_Agent` `861db00`, deployed, RUNNING):** encoded approximate
cohort sizes + an explicit rule into the "## Dataset Selection Heuristics"
section — 'largest' = most samples, 'curated' = has a curated PDAC subset;
RNA-seq sizes (paca_ca_rnaseq ~262, tcga_paad 185/150-curated, cptac_pda ~131,
paca_au_rnaseq ~92); 'largest curated RNA-seq' → tcga_paad, 'largest RNA-seq'
→ paca_ca_rnaseq, 'largest cohort' (any modality) → gse71729_moffitt; and do
NOT pick a smaller cohort for subtype labels unless subtypes were requested.
(A heavier alternative — add a real `n_samples` field to every biodata-registry
manifest and surface it — was deferred as over-engineering; sizes are stable.)

**Narrow fabrication backstop (`research-coordinator` `8ae021b`).** Per the
agreed "keep prompt rules primary, add one narrow code guard" plan:
`ResearchRouter.flag_unbacked_numbers(response, trace)` returns True only when a
response has a results-table-sized cluster of numbers (>=8 decimals) AND the
trace has no tool output; `run_eval.py` forces FAIL when it fires. Verified it
does NOT trip on refusals/clarifications, flags a real solution only when its
trace is empty, and passes it when the trace has real tool output. Deliberately
NOT made the primary enforcer / NOT put in the agent's `should_continue` loop —
a blunt "no solution without execution" rule would break legitimate
non-execution answers (out-of-scope, REQUEST_REQUIRED_INPUT, FLAG_LIMITATION,
conceptual).

**ANS-021: decided NOT to fix.** The PARTIAL is acceptable — it already
satisfies REQUEST_REQUIRED_INPUT (asks for the ranked list correctly); the only
gap is it didn't do partial setup first / over-argued GSEA scope (GSEA IS
supported via `decoupler_run_individual_methods`). Judged too minor/edge-case to
warrant a prompt change (user agreed it risked over-engineering). Left as-is.

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
