---
title: Research Coordinator
emoji: 🔬
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "4.44.0"
app_file: app.py
pinned: false
---

# Research Coordinator

A lightweight Gradio application that acts as an orchestrating router for multi-omics bioinformatics analysis.

## What it does

```
User → Research Coordinator (Gradio UI)
         ├── Claude API  — fast answers for conceptual / interpretive questions
         └── gradio_client → Specialist Agent HF Spaces (computation)
```

The coordinator classifies every incoming message with a quick Claude API call:

| Route | Examples |
|-------|---------|
| **Direct** (Claude API) | "What does TP53 do?", "Explain these fold-change values", "What is PROGENy?" |
| **Specialist** (gradio_client) | "Run DE between subtypes", "How many samples in GSE71729?", "Load the Moffitt dataset" |

After a specialist returns results, the coordinator summarizes them in plain scientific language.

## Relationship to DecoupleRpy Agent

The **DecoupleRpy Agent** (`anne-voigt/Paper2Agent_decoupleRpy`) is the primary specialist. It handles:
- Differential expression (limma / t-test)
- TF activity inference (CollecTRI via decoupleR)
- Pathway scoring (PROGENy)
- Gene set enrichment (Hallmark / MSigDB)
- GEO data loading and metadata queries

This coordinator is intentionally thin — it adds routing intelligence and conversational context without duplicating any analysis logic.

## Running locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Anthropic API key (never commit this)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Launch
python app.py
```

The app will open at `http://localhost:7860`.

## Adding a new specialist agent

Edit `agents.yaml` and add an entry under `agents:`:

```yaml
- id: my_agent
  name: "My Specialist Agent"
  description: "What this agent does"
  hf_space: "your-hf-org/your-space-name"
  trigger_keywords:
    - "keyword one"
    - "keyword two"
  capabilities:
    - my_capability
```

Then update the `routing_prompt` in `prompts.yaml` to include conditions that route to `"agent_id": "my_agent"`.

No code changes are needed in `router.py` for the dispatch itself — it reads `hf_space` from the registry automatically.

## HuggingFace Spaces deployment

Set `ANTHROPIC_API_KEY` as a Space secret (Settings → Repository secrets). The app entry point is `app.py`.

## File overview

| File | Purpose |
|------|---------|
| `app.py` | HF Spaces entry point |
| `gradio_ui.py` | Gradio chat interface |
| `router.py` | Routing logic (Claude classify + dispatch) |
| `agents.yaml` | Registry of specialist agents |
| `prompts.yaml` | System prompts for coordinator and routing |
| `requirements.txt` | Python dependencies |
