"""
Gradio chat interface for the Research Coordinator.

Routing decisions are shown inline so the user always knows whether
Claude answered directly or a specialist agent was dispatched.
"""
import logging
import gradio as gr
from router import ResearchRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded fallback dataset list — used when biodata_registry is not
# installed and the specialist HF Space is unavailable at startup.
# ---------------------------------------------------------------------------
_FALLBACK_DATASETS = [
    {"dataset_id": "gse71729_moffitt",   "label": "Moffitt 2015 — GSE71729"},
    {"dataset_id": "tcga_paad",           "label": "TCGA-PAAD"},
    {"dataset_id": "paca_au_rnaseq",      "label": "ICGC PACA-AU RNA-seq"},
    {"dataset_id": "paca_au_array",       "label": "ICGC PACA-AU Array"},
    {"dataset_id": "puleo_2018",          "label": "Puleo 2018 — 309 samples"},
    {"dataset_id": "gse28735_pdac",       "label": "Zhang 2012 — GSE28735"},
    {"dataset_id": "gse16515_mayo",       "label": "Mayo — GSE16515"},
    {"dataset_id": "gse62165_jiang",      "label": "Jiang 2015 — GSE62165"},
    {"dataset_id": "gse71989_chen",       "label": "Chen 2016 — GSE71989"},
    {"dataset_id": "gse15471_badea",      "label": "Badea 2008 — GSE15471"},
    {"dataset_id": "gse21501_stratford",  "label": "Stratford 2010 — GSE21501"},
    {"dataset_id": "gse57495",            "label": "GSE57495 (OS cohort)"},
    {"dataset_id": "gse17891_collisson",  "label": "Collisson 2011 — GSE17891"},
    {"dataset_id": "paca_ca_rnaseq",      "label": "ICGC PACA-CA RNA-seq"},
    {"dataset_id": "cptac_pda",           "label": "CPTAC-PDA"},
    {"dataset_id": "gse50827_nones",      "label": "Nones 2014 — GSE50827"},
]


def _fetch_dataset_choices() -> list[tuple[str, str]]:
    """Return list of (label, dataset_id) tuples for the dropdown.

    Tries biodata_registry import first; falls back to hardcoded list.
    Returns tuples so gr.Dropdown can show human-readable labels while
    storing dataset_id as the value.
    """
    try:
        from biodata_registry import list_available_datasets
        datasets = list_available_datasets()
        choices = []
        for d in datasets:
            label = d.get("title", d["dataset_id"])
            # Trim long titles — keep accession at front for scannability
            accession = d.get("accession", "")
            if accession and accession not in label:
                label = f"{accession} — {label}"
            choices.append((label, d["dataset_id"]))
        logger.info("Dataset dropdown populated from biodata_registry (%d datasets)", len(choices))
        return choices
    except Exception as exc:
        logger.warning("biodata_registry unavailable (%s); using fallback dataset list.", exc)
        return [(d["label"], d["dataset_id"]) for d in _FALLBACK_DATASETS]


class CoordinatorUI:
    def __init__(self):
        self._router = ResearchRouter()
        self._dataset_choices = _fetch_dataset_choices()

    # ------------------------------------------------------------------
    # Chat handler
    # ------------------------------------------------------------------

    def _respond(self, message: str, history: list, selected_datasets: list):
        """Handle one user turn. Yields (history, "") pairs for streaming."""
        if not message.strip():
            yield history, ""
            return

        # 1. Classify the message
        classification = self._router.classify(message)
        route = classification.get("route", "direct")
        agent_id = classification.get("agent_id")
        reasoning = classification.get("reasoning", "")

        if route == "specialist" and agent_id:
            agent_name = self._router.agent_display_name(agent_id)

            # Show routing notification immediately
            routing_note = (
                f"_Routing to **{agent_name}** for computation — this may take a moment._\n\n"
                f"_{reasoning}_"
            )
            history = history + [{"role": "user", "content": message},
                                  {"role": "assistant", "content": routing_note}]
            yield history, ""

            # Dispatch and get result, passing dataset constraint if set
            all_ids = [v for _, v in self._dataset_choices]
            constraint = selected_datasets if selected_datasets and set(selected_datasets) != set(all_ids) else None
            result = self._router.dispatch_to_specialist(agent_id, message, dataset_constraint=constraint)

            full_response = (
                f"_Routing to **{agent_name}** for computation._\n\n"
                f"**Result from {agent_name}:**\n\n{result}"
            )
            history[-1]["content"] = full_response
            yield history, ""

        else:
            # Direct Claude response — stream it
            history = history + [{"role": "user", "content": message},
                                  {"role": "assistant", "content": ""}]
            yield history, ""

            accumulated = ""
            # Build plain history for the API (exclude the current turn)
            plain_history = [
                (h["content"] if h["role"] == "user" else None,
                 h["content"] if h["role"] == "assistant" else None)
                for h in history[:-2]
            ]
            for chunk in self._router.direct_response(message, plain_history):
                accumulated += chunk
                history[-1]["content"] = accumulated
                yield history, ""


    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build(self) -> gr.Blocks:
        all_ids = [v for _, v in self._dataset_choices]

        with gr.Blocks(title="Research Coordinator") as demo:
            gr.Markdown(
                """# 🔬 Research Coordinator

A lightweight orchestrating assistant for multi-omics bioinformatics.
Conceptual questions are answered directly; computation is dispatched to specialist agents.
"""
            )

            chatbot = gr.Chatbot(
                label="Conversation",
                height=520,
                show_label=False,
            )

            with gr.Accordion("Dataset Selection (optional)", open=False):
                gr.Markdown(
                    "_Select datasets to constrain analysis. Leave empty (or select all) to use the full registry._"
                )
                dataset_selector = gr.Dropdown(
                    choices=self._dataset_choices,
                    value=all_ids,
                    multiselect=True,
                    label="Active datasets",
                    info=f"{len(self._dataset_choices)} datasets available",
                    show_label=True,
                )

            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder="Ask a biology question or request an analysis…",
                    show_label=False,
                    scale=8,
                    container=False,
                )
                submit_btn = gr.Button("Send", variant="primary", scale=1)

            gr.Examples(
                examples=[
                    "What does TP53 do in pancreatic cancer?",
                    "Run differential expression between classical and basal subtypes in the Moffitt dataset",
                    "What is PROGENy and how does it work?",
                    "How many samples are in GSE71729?",
                    "Explain what TF activity scores mean biologically",
                ],
                inputs=msg_box,
                label="Example questions",
            )

            gr.Markdown(
                "_Direct answers via Claude API · Computation via specialist agents_",
            )

            # Wire up interactions
            submit_btn.click(
                fn=self._respond,
                inputs=[msg_box, chatbot, dataset_selector],
                outputs=[chatbot, msg_box],
            )
            msg_box.submit(
                fn=self._respond,
                inputs=[msg_box, chatbot, dataset_selector],
                outputs=[chatbot, msg_box],
            )

        return demo


if __name__ == "__main__":
    ui = CoordinatorUI()
    ui.build().launch()
