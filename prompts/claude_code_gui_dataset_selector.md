# Claude Code Prompt: GUI Dataset Selector

Add a dataset selector to the research-coordinator Gradio UI. This is a focused,
self-contained feature — changes are limited to `gradio_ui.py` and `router.py`.
No changes to manifests, the specialist agent, or biodata-registry.

---

## Architecture Context

The research-coordinator is a Gradio app that routes user messages to either:
- Claude API directly (conceptual/interpretive questions)
- The DecoupleRpy specialist agent via `gradio_client` (any computation or dataset question)

The specialist agent already has all registered datasets injected into its system
prompt at every call via `get_system_prompt()`. It knows what datasets exist.
What's missing is a way for the user to constrain which datasets the specialist
should use for a given session or question.

Relevant files:
- `gradio_ui.py` — Gradio interface definition
- `router.py` — routing logic; constructs the message sent to the specialist
- `prompts.yaml` — system prompts; `coordinator_system_prompt` and `routing_prompt`

---

## What to Build

### 1. Dataset multiselect in the Gradio UI (`gradio_ui.py`)

Add a `gr.Dropdown` with `multiselect=True` populated from the live dataset registry.

```python
# At app startup, fetch available dataset IDs from the specialist
# Use these to populate the dropdown choices
# Default: all datasets selected (no constraint = use all)
```

Requirements:
- Choices should be human-readable: show dataset title + sample count, not just ID
  e.g. "Moffitt 2015 — GSE71729 (357 samples)" → value: "gse71729_moffitt"
- Default state: all datasets selected
- Placement: below the chatbot, above the message input — or in a collapsible
  `gr.Accordion` labeled "Dataset Selection (optional)" to keep the UI clean
- The selection persists for the session (use `gr.State` if needed)
- Empty selection = same as all selected (no constraint)

### 2. Pass selection through routing (`router.py`)

When the user sends a message, include the selected dataset IDs in the context
sent to the specialist. The simplest approach: prepend a system note to the
routed message.

```python
# If datasets are selected (not all / not empty):
# Prepend to the specialist message:
# "[Dataset constraint: user has restricted analysis to: gse71729_moffitt, tcga_paad.
#   Only use these datasets unless the user explicitly asks for others.]"

# If no selection or all selected:
# Send message as-is, no constraint added
```

The specialist's existing system prompt instructs it to only use datasets from
the registry — this constraint narrows that further without requiring any
changes to the specialist or its prompts.

### 3. Fetch dataset list at startup

The dropdown needs to be populated with current dataset IDs and titles. Options
in order of preference:

1. **Import directly**: `from biodata_registry import list_available_datasets`
   if biodata-registry is installed in the coordinator's environment
2. **Query the specialist**: use `gradio_client` to call `dataset_list_available`
   on the specialist HF Space at startup
3. **Fallback hardcoded list**: if neither is available at startup, use a
   static list that can be manually updated — acceptable fallback, note it as
   a limitation

Use option 1 if available, option 2 otherwise. Do not block app startup if the
specialist is unavailable — catch the exception, log a warning, and fall back
to option 3.

---

## Edge Cases to Handle

- **Specialist unavailable at startup**: Graceful fallback to hardcoded list,
  UI still loads
- **Empty selection**: Treat identically to "all selected" — no constraint sent
- **Single dataset selected**: Valid — specialist should only use that dataset
  and say so explicitly in its response if the question would normally use others
- **Selection changes mid-conversation**: Apply to the next message only;
  do not retroactively affect prior turns

---

## What NOT to Build (yet)

Do not build intelligent auto-selection logic in this PR — that is a separate
feature. This feature is purely user-driven selection. The agent should not
override or second-guess the user's dataset constraint.

Do not change `prompts.yaml`, the specialist agent, or biodata-registry.

---

## Success Criteria

- Dropdown appears in the UI, populated with dataset names from the live registry
- Selecting a subset causes the specialist to only use those datasets in its response
- Selecting nothing (or all) produces identical behavior to the current app
- App starts successfully even if the specialist HF Space is unavailable
- No changes to any file outside `gradio_ui.py` and `router.py`
  (plus `requirements.txt` if a new dep is needed)
- Existing routing behavior is unchanged for messages sent with no dataset constraint

---

## Testing

Manually verify these cases before pushing:
1. No selection → same output as current app on a dataset question
2. Single dataset selected → specialist acknowledges the constraint and uses only that dataset
3. All datasets selected → same output as current app
4. App startup with specialist HF Space unavailable → UI loads with fallback list, warning logged
