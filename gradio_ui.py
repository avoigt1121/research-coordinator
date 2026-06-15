"""
Gradio chat interface for the Research Coordinator.

Routing decisions are shown inline so the user always knows whether
Claude answered directly or a specialist agent was dispatched.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
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

    # Placeholders for the three read-only transparency dropdowns.
    _NO_DATA_NOTE = "_No dataset-loading steps yet._"
    _NO_CODE_NOTE = "_No code has been executed yet._"
    _NO_LOGIC_NOTE = "_No analysis steps yet._"

    def _empty_panels(self) -> tuple[str, str, str]:
        """Placeholder (data, code, logic) markdown for a cleared/idle state."""
        return self._NO_DATA_NOTE, self._NO_CODE_NOTE, self._NO_LOGIC_NOTE

    def _render_panels(self, panels: dict) -> tuple[str, str, str]:
        """Map a router {"data","code","logic"} dict to (data, code, logic)
        markdown, substituting the placeholder note for any empty bucket."""
        return (
            panels.get("data") or self._NO_DATA_NOTE,
            panels.get("code") or self._NO_CODE_NOTE,
            panels.get("logic") or self._NO_LOGIC_NOTE,
        )

    def _dispatch_specialist(self, history: list, agent_id: str, message: str,
                              selected_datasets: list, reasoning: str | None = None):
        """Append a routing notice to `history`, dispatch to the specialist, then
        fill in the result. Yields (history, "", panels, code_accordion) tuples
        for streaming, where `panels` is a (data_md, code_md, logic_md) triple
        feeding the three read-only transparency dropdowns. The fourth element is
        always gr.skip() (the Code panel is left as the user set it — the live
        code is shown inline in the chat bubble instead of by auto-opening it).

        Expects `history[-1]` to be a placeholder assistant message. The panels
        are reset (clearing any previous run's trace), then while the agent works
        the chat bubble shows the executing code inline, settling to the polished
        final answer when done. Full detail persists in the Data/Code/Logic
        dropdowns.
        """
        agent_name = self._router.agent_display_name(agent_id)

        routing_note = f"_Routing to **{agent_name}** for computation — this may take a moment._"
        if reasoning:
            routing_note += f"\n\n_{reasoning}_"
        status_note = self._router.specialist_status_note(agent_id)
        if status_note:
            routing_note += f"\n\n{status_note}"
        history[-1]["content"] = routing_note
        # New run → clear the previous run's panels.
        panels = self._empty_panels()
        yield history, "", panels, gr.skip()

        # Stream the specialist's steps live. dispatch_to_specialist_stream
        # yields (display_text, trace, panels, done) frames as the agent works;
        # the panels bucketing is pure post-processing of the chatbot history
        # already on the wire (no extra calls/latency) and feeds the three
        # transparency dropdowns. `display_text` is the executing code inline for
        # progress frames, and the polished answer when done.
        all_ids = [v for _, v in self._dataset_choices]
        constraint = selected_datasets if selected_datasets and set(selected_datasets) != set(all_ids) else None

        for text, _trace, raw_panels, done in self._router.dispatch_to_specialist_stream(
            agent_id, message, dataset_constraint=constraint
        ):
            if raw_panels and any(raw_panels.values()):
                panels = self._render_panels(raw_panels)
            if done:
                history[-1]["content"] = (
                    f"_Routing to **{agent_name}** for computation._\n\n"
                    f"**Result from {agent_name}:**\n\n{text}"
                )
            else:
                # Live: show the executing code inline while the agent works.
                history[-1]["content"] = f"**{agent_name} is working…**\n\n{text}"
            yield history, "", panels, gr.skip()

    def _respond(self, message: str, history: list, selected_datasets: list,
                  pending_specialist: dict | None,
                  data_md: str, code_md: str, logic_md: str):
        """Handle one user turn. Yields
        (history, "", pending_specialist, data_md, code_md, logic_md) tuples.

        The last three are the read-only Data / Code / Logic transparency
        dropdowns; they pass through unchanged on direct/clarify turns and are
        refreshed live by _dispatch_specialist on a specialist computation."""
        panels = (data_md, code_md, logic_md)
        if not message.strip():
            yield history, "", pending_specialist, *panels, gr.skip()
            return

        # 0. If a dataset-specification prompt is pending, check whether this
        # message answers it (names a dataset, or says "no preference").
        if pending_specialist:
            reply_info = self._router.classify_dataset_reply(
                pending_specialist["message"], message, self._dataset_choices
            )
            if reply_info.get("is_reply"):
                note = reply_info.get("preference_note")
                combined_message = pending_specialist["message"]
                if note:
                    combined_message = f"{note}\n\n{combined_message}"
                agent_id = pending_specialist["agent_id"]

                history = history + [{"role": "user", "content": message},
                                      {"role": "assistant", "content": ""}]
                for h, m, p, acc in self._dispatch_specialist(history, agent_id, combined_message, selected_datasets):
                    yield h, m, None, *p, acc
                return
            # Doesn't look like a reply to the pending prompt — drop it and
            # classify this message fresh as a new question.
            pending_specialist = None

        # 1. Classify the message
        classification = self._router.classify(message)
        route = classification.get("route", "direct")
        agent_id = classification.get("agent_id")
        dataset_status = classification.get("dataset_status")
        reasoning = classification.get("reasoning", "")

        if route == "specialist" and agent_id:
            if dataset_status == "unspecified":
                agent_name = self._router.agent_display_name(agent_id)
                clarify_msg = (
                    f"_This will go to the **{agent_name}**, but no dataset was specified._\n\n"
                    "You can pick one from the **Dataset Selection** panel above and re-send "
                    "your question, or just reply **\"no preference\"** and I'll let the "
                    "specialist choose the best fit and explain why."
                )
                history = history + [{"role": "user", "content": message},
                                      {"role": "assistant", "content": clarify_msg}]
                yield history, "", {"message": message, "agent_id": agent_id}, *panels, gr.skip()
                return

            history = history + [{"role": "user", "content": message},
                                  {"role": "assistant", "content": ""}]
            for h, m, p, acc in self._dispatch_specialist(history, agent_id, message, selected_datasets, reasoning):
                yield h, m, None, *p, acc

        else:
            # Direct Claude response — stream it
            history = history + [{"role": "user", "content": message},
                                  {"role": "assistant", "content": ""}]
            yield history, "", None, *panels, gr.skip()

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
                yield history, "", None, *panels, gr.skip()


    # ------------------------------------------------------------------
    # Session save / load
    # ------------------------------------------------------------------

    def _save_session(self, history: list, data_md: str, code_md: str, logic_md: str) -> str:
        """Serialize chatbot history (and the latest panels) to a temp JSON file."""
        if not history:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = tempfile.NamedTemporaryFile(
            suffix=f"_research_session_{timestamp}.json",
            delete=False,
            mode="w",
        )
        json.dump(
            {"history": history,
             "panels": {"data": data_md, "code": code_md, "logic": logic_md}},
            tmp, indent=2,
        )
        tmp.close()
        return tmp.name

    def _load_session(self, filepath) -> tuple[list, str, str, str]:
        """Deserialize a session JSON file back into
        (history, data_md, code_md, logic_md).

        Accepts the current {"history", "panels"} format, the older
        {"history", "call_log"} format (call_log maps to the Code panel), and
        the oldest plain-list format (panels default to placeholders).
        """
        d, c, lg = self._empty_panels()
        if filepath is None:
            return [], d, c, lg
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data, d, c, lg
            if isinstance(data, dict):
                history = data.get("history", [])
                if not isinstance(history, list):
                    return [], d, c, lg
                panels = data.get("panels")
                if isinstance(panels, dict):
                    d, c, lg = self._render_panels(panels)
                elif data.get("call_log"):
                    # Back-compat: the old single trace maps to the Code panel.
                    c = data["call_log"]
                return history, d, c, lg
            return [], d, c, lg
        except Exception as exc:
            logger.warning("Failed to load session file: %s", exc)
            return [], d, c, lg

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build(self) -> gr.Blocks:
        all_ids = [v for _, v in self._dataset_choices]

        with gr.Blocks(title="Research Coordinator") as demo:
            gr.Markdown(
                """# Research Coordinator

A lightweight orchestrating assistant for multi-omics bioinformatics.
Conceptual questions are answered directly; computation is dispatched to specialist agents.
"""
            )

            chatbot = gr.Chatbot(
                label="Conversation",
                height=520,
                show_label=False,
            )

            # Holds {"message": ..., "agent_id": ...} when the coordinator has
            # asked the user to specify a dataset and is awaiting their reply.
            pending_specialist = gr.State(value=None)

            # Three read-only transparency dropdowns, collapsed by default.
            # All three are filled from the same specialist response already on
            # the wire (see ResearchRouter._extract_panels) — no extra latency.
            gr.Markdown(
                "_Behind each answer: expand to see **what data** was used, "
                "**what code** ran, and the **reasoning** the specialist followed._"
            )
            with gr.Accordion("Data used", open=False):
                gr.Markdown(
                    "_Datasets, loaders, source references, and sample counts "
                    "the specialist touched in the most recent computation._"
                )
                data_panel = gr.Markdown(self._NO_DATA_NOTE)
            # Named so we can auto-expand it live while the specialist runs
            # (see _dispatch_specialist) — it carries the meatiest substance.
            code_accordion = gr.Accordion("Code used", open=False)
            with code_accordion:
                gr.Markdown(
                    "_The actual code the specialist executed, with its outputs._"
                )
                code_panel = gr.Markdown(self._NO_CODE_NOTE)
            with gr.Accordion("Logic / reasoning", open=False):
                gr.Markdown(
                    "_The step-by-step reasoning the specialist followed to reach "
                    "the answer._"
                )
                logic_panel = gr.Markdown(self._NO_LOGIC_NOTE)

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

            with gr.Accordion("Save / Load Session (optional)", open=False):
                gr.Markdown(
                    "_Download the current conversation as JSON, or upload a previous session to continue it._"
                )
                with gr.Row():
                    save_btn = gr.Button("Download session", variant="secondary", scale=1)
                    session_file = gr.File(
                        label="Upload session",
                        file_types=[".json"],
                        scale=2,
                    )
                download_file = gr.File(label="Session file", visible=False)

            gr.Markdown(
                "_Direct answers via Claude API · Computation via specialist agents_",
            )

            # Wire up interactions
            panel_components = [data_panel, code_panel, logic_panel]
            submit_btn.click(
                fn=self._respond,
                inputs=[msg_box, chatbot, dataset_selector, pending_specialist, *panel_components],
                outputs=[chatbot, msg_box, pending_specialist, *panel_components, code_accordion],
            )
            msg_box.submit(
                fn=self._respond,
                inputs=[msg_box, chatbot, dataset_selector, pending_specialist, *panel_components],
                outputs=[chatbot, msg_box, pending_specialist, *panel_components, code_accordion],
            )
            save_btn.click(
                fn=self._save_session,
                inputs=[chatbot, *panel_components],
                outputs=[download_file],
            ).then(
                fn=lambda p: gr.File(value=p, visible=p is not None),
                inputs=[download_file],
                outputs=[download_file],
            )
            session_file.upload(
                fn=self._load_session,
                inputs=[session_file],
                outputs=[chatbot, *panel_components],
            )

        return demo


if __name__ == "__main__":
    ui = CoordinatorUI()
    ui.build().launch()
