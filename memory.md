# memory.md — Research Coordinator Working State

Last updated: 2026-06-09

---

## Current State

Deployed and functional. Both GitHub and HF are in sync as of 2026-06-02.
Last commit: `90a1547` — "Add Scientific Interpretation Rules to coordinator system prompt"

---

## What Was Done Recently

- Added routing rules for capability/dataset questions (routes to specialist, not answered directly)
- Added Scientific Interpretation Rules to `coordinator_system_prompt` (hedged language, no unsupported clinical claims)
- Fixed result extraction: finds "Final Solution" message, skips HF log notice
- Fixed dispatch: two-step call — set query state via `/lambda`, then `/interact_with_agent`

---

## Known Issues / Next Steps

### 1. Routing is keyword-based — fragile
The `routing_prompt` uses a list of trigger conditions. Ambiguous questions can misroute.
No automated test suite for routing decisions.
**Planned**: Add a routing test battery with expected route per message.

### 2. No error handling for specialist timeout
If `anne-voigt/Paper2Agent_decoupleRpy` is sleeping (HF free tier), the gradio_client
call times out with no user-friendly message.
**Planned**: Add timeout handling with a "specialist is starting up, retry in ~30s" message.

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

---

## Git / Deployment State

| Remote | URL | Status |
|--------|-----|--------|
| `origin` | `github.com/avoigt1121/research-coordinator` | In sync |
| `hf` | `huggingface.co/spaces/anne-voigt/research_coordinator` | In sync |

To push changes: commit locally → `git push origin main` → `git push hf main`
