"""
Gradio chat interface for the Research Coordinator.

Routing decisions are shown inline so the user always knows whether
Claude answered directly or a specialist agent was dispatched.
"""
import gradio as gr
from router import ResearchRouter


class CoordinatorUI:
    def __init__(self):
        self._router = ResearchRouter()

    # ------------------------------------------------------------------
    # Chat handler
    # ------------------------------------------------------------------

    def _respond(self, message: str, history: list):
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

            # Dispatch and get result
            result = self._router.dispatch_to_specialist(agent_id, message)

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
                inputs=[msg_box, chatbot],
                outputs=[chatbot, msg_box],
            )
            msg_box.submit(
                fn=self._respond,
                inputs=[msg_box, chatbot],
                outputs=[chatbot, msg_box],
            )

        return demo


if __name__ == "__main__":
    ui = CoordinatorUI()
    ui.build().launch()
