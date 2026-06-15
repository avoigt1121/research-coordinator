# Research Coordinator — Architecture

Stable architecture reference. Current status → `memory.md`.

---

## What This Repo Is

A lightweight Gradio application that acts as the **orchestrating router** for the
PDAC research agent system. It is the front door — the user-facing layer that
classifies every message and either answers directly or hands off to a specialist.

**It does NOT do computation.** No pandas, no scanpy, no statistical tests.
Those belong in specialist agents.

---

## Two-Tier Routing Architecture

```
User message
  └── router.py: classify with Claude API (fast, cheap)
        ├── "direct"       → answer with Claude API (conceptual/interpretive)
        ├── "out_of_scope" → decline with a scope explanation (wet-lab/protocol
        │                    design); answered via Claude using the "## Scope"
        │                    section of coordinator_system_prompt
        └── "specialist"   → gradio_client → DecoupleRpy Agent HF Space
                              └── waits for result
                                    └── coordinator summarizes result
```

### What routes "direct"
- Conceptual biology questions ("what does TP53 do?")
- Interpretation of already-returned results
- General methods/statistics questions

### What routes "out_of_scope"
- Wet-lab / bench protocol design (qPCR primers, cloning, CRISPR guides,
  antibody/reagent selection) — declined with an explanation that the system
  is scoped to PDAC transcriptomic analysis. (Implemented 2026-06-14.)
- `out_of_scope` carries `dataset_status: null` and is handled like a direct
  answer (streamed via `direct_response`), so no extra dispatch code path —
  the decline behavior comes from the `## Scope` system-prompt section.

### What routes to "specialist"
- Any computation: DE, enrichment, pathway scoring, TF activity
- Any dataset question: metadata, sample counts, what datasets exist
- Loading or processing data
- Capability questions about the DecoupleRpy agent

**Key rule**: The coordinator does NOT know what datasets are registered.
It always routes dataset/capability questions to the specialist.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | HF Spaces entry point |
| `gradio_ui.py` | Gradio chat interface |
| `router.py` | Routing logic: Claude classify → dispatch |
| `agents.yaml` | Registry of specialist agents (id, hf_space, trigger_keywords) |
| `prompts.yaml` | System prompts: `coordinator_system_prompt`, `routing_prompt` |
| `requirements.txt` | Python dependencies |
| `.env` | Local dev only — never commit. Set `ANTHROPIC_API_KEY`. |
| `.github/workflows/sync-to-hf-space.yml` | Auto-syncs `origin/main` → the `hf` Space on every push (checkout@v5; push step retries with backoff) |
| `eval/` | Offline eval harness: `run_eval.py` dispatches a question bank through the router + specialist and LLM-judges each response. `pilot_questions.json` (18) / `pilot_fresh10.json` (10) sampled from the 109-question source bank; `results/` holds timestamped raw/graded/report files. The judge grades against the captured specialist execution trace (so it can tell real computation from fabrication), with a deterministic `flag_unbacked_numbers` backstop. |

---

## Deployment

- **HF Space**: `anne-voigt/research_coordinator`
- **Sync**: Automatic — `.github/workflows/sync-to-hf-space.yml` force-pushes
  `origin/main` to the `hf` remote on every push to `main` (also runnable
  manually via `workflow_dispatch`). Requires a one-time `HF_TOKEN` repo
  secret (write access to the Space) — see the workflow file for setup steps.
- **`origin` is the source of truth** — do not push directly to `hf`; the
  next push to `main` will force-overwrite it.
- **Both remotes configured**: `origin` = GitHub, `hf` = HF Space (kept for
  emergency/manual pushes only)
- **HF secret**: `ANTHROPIC_API_KEY` must be set in Space settings (separate
  from the `HF_TOKEN` GitHub Actions secret above)

### Branch & deploy safety (read `DEPLOYMENT.md`)

- **`main` IS production.** The sync Action triggers on `push` to `main` only,
  so pushing **`main`** deploys to the live Space; pushing **`dev`** (or any other
  branch) does **not**. Do all work on `dev`; promote to `main` only to release.
- **Default to dev. Never push `main` unless the user explicitly asks to deploy
  to prod.** Full workflow, dev-Space setup, and the "am I about to deploy?"
  checklist live in `DEPLOYMENT.md`.

---

## Adding a New Specialist Agent

1. Add entry to `agents.yaml` (id, name, description, hf_space, trigger_keywords)
2. Update `routing_prompt` in `prompts.yaml` to add routing conditions
3. No changes needed in `router.py` — it reads `hf_space` dynamically

---

## Key Design Decisions

**Why keep the coordinator thin?**
It adds routing intelligence and conversational framing without duplicating
analysis logic. If it went down, users could query the specialist directly.

**Why not let the coordinator answer dataset questions?**
`dataset_list_available()` in the specialist returns runtime truth. The coordinator
would answer from training knowledge, which drifts. Routing guarantees accuracy.
