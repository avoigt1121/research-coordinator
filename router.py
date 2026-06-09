"""
Routes user messages to either:
  - Direct Claude API response (fast, conceptual questions)
  - Specialist agent via gradio_client (computation questions)
"""
from __future__ import annotations

import json
import yaml
from pathlib import Path
from anthropic import Anthropic

try:
    from gradio_client import Client as GradioClient
    GRADIO_CLIENT_AVAILABLE = True
except ImportError:
    GRADIO_CLIENT_AVAILABLE = False


class ResearchRouter:
    def __init__(
        self,
        agents_yaml: str = "agents.yaml",
        prompts_yaml: str = "prompts.yaml",
    ):
        base = Path(__file__).parent
        with open(base / agents_yaml) as f:
            self._agents_cfg = yaml.safe_load(f)
        with open(base / prompts_yaml) as f:
            self._prompts_cfg = yaml.safe_load(f)

        # Build a quick lookup by agent id
        self._agents = {a["id"]: a for a in self._agents_cfg["agents"]}

        import os
        # HF Space secret is named "Anthropic_API_KEY" (matches DecoupleRpy Space)
        api_key = os.environ.get("Anthropic_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        self._client = Anthropic(api_key=api_key)
        self._model = "claude-sonnet-4-6"

        self._system_prompt = self._prompts_cfg["coordinator_system_prompt"]
        self._routing_prompt = self._prompts_cfg["routing_prompt"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, message: str) -> dict:
        """Call Claude to classify: direct vs specialist.

        Returns a dict with keys: route, agent_id, reasoning.
        Falls back to "direct" on any parse error so the user always gets
        a response.
        """
        prompt = f"{self._routing_prompt}\n\nUser message: {message}"
        response = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"route": "direct", "agent_id": None, "reasoning": "parse error — defaulting to direct"}

    def direct_response(self, message: str, history: list):
        """Stream a direct Claude API response.

        history: list of (user_str, assistant_str) tuples (Gradio format).
        Yields text chunks as they arrive.
        """
        messages = []
        for user_msg, assistant_msg in history:
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({"role": "user", "content": message})

        with self._client.messages.stream(
            model=self._model,
            max_tokens=2048,
            system=self._system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text

    def dispatch_to_specialist(self, agent_id: str, message: str, dataset_constraint: list | None = None) -> str:
        """Send message to specialist HF Space via gradio_client and return result.

        Phase 1: real dispatch is implemented; the Space may be cold so we
        wrap in try/except and return a helpful stub on failure.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return f"[Error] Unknown agent: {agent_id}"

        hf_space = agent["hf_space"]

        # Prepend dataset constraint note if user restricted selection
        if dataset_constraint:
            ids = ", ".join(dataset_constraint)
            constraint_note = (
                f"[Dataset constraint: the user has restricted analysis to the following "
                f"datasets: {ids}. Only use these datasets unless the user explicitly asks "
                f"for others.]\n\n"
            )
            message = constraint_note + message

        if not GRADIO_CLIENT_AVAILABLE:
            return (
                f"[Stub] gradio_client is not installed. "
                f"Would dispatch to {agent['name']} ({hf_space}) with: {message}"
            )

        try:
            gc = GradioClient(hf_space)
            # DecoupleRpy's interact_with_agent reads the query from a hidden gr.State.
            # Step 1: call /lambda to set that state for this session.
            gc.predict(x=message, api_name="/lambda")
            # Step 2: call /interact_with_agent with empty history — query comes from state.
            result = gc.predict(
                chatbot_history=[],
                api_name="/interact_with_agent",
            )
            # result is the full updated chatbot history.
            # Find the Final Solution message; fall back to the last substantive assistant message.
            if isinstance(result, list) and result:
                solution = None
                last_assistant = None
                for msg in result:
                    if not isinstance(msg, dict) or msg.get("role") != "assistant":
                        continue
                    content = msg.get("content", "") or ""
                    if not content.strip():
                        continue
                    # Skip the HF log-link notice
                    if "Full run log saved" in content or "huggingface.co/datasets" in content:
                        continue
                    last_assistant = content
                    if "Final Solution" in content or "solution-content" in content:
                        solution = content
                if solution:
                    return solution
                if last_assistant:
                    return last_assistant
            return str(result)
        except Exception as exc:
            return (
                f"[{agent['name']}] The specialist agent could not be reached "
                f"(Space may be cold or loading). Error: {exc}\n\n"
                "Please try again in a moment, or rephrase your question for a direct answer."
            )

    def agent_display_name(self, agent_id: str) -> str:
        agent = self._agents.get(agent_id, {})
        return agent.get("name", agent_id)
