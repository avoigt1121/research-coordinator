"""
Routes user messages to either:
  - Direct Claude API response (fast, conceptual questions)
  - Specialist agent via gradio_client (computation questions)
"""
from __future__ import annotations

import json
import yaml
import httpx
from pathlib import Path
from anthropic import Anthropic

try:
    from gradio_client import Client as GradioClient
    GRADIO_CLIENT_AVAILABLE = True
except ImportError:
    GRADIO_CLIENT_AVAILABLE = False

# Safety cap on how many times dispatch_to_specialist will click "Continue"
# (via /handle_continue) when the agent hits its step limit. Each continue
# grants 15 more steps, so this allows up to MAX_CONTINUES * 15 extra steps.
MAX_CONTINUES = 10

# Bound how long dispatch_to_specialist's gradio_client calls can hang —
# without this, a cold/sleeping HF Space causes an indefinite hang instead
# of the friendly "could not be reached" message.
SPECIALIST_TIMEOUT_SECONDS = 120


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

        Returns a dict with keys: route, agent_id, dataset_status, reasoning.
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
            return {
                "route": "direct",
                "agent_id": None,
                "dataset_status": None,
                "reasoning": "parse error — defaulting to direct",
            }

    def classify_dataset_reply(self, pending_message: str, reply: str,
                                dataset_choices: list[tuple[str, str]]) -> dict:
        """Check whether `reply` answers a pending dataset-specification prompt.

        Returns a dict with keys:
          - "is_reply": True if `reply` names a dataset/cohort from
            `dataset_choices`, or says the user has no preference. False if
            it looks like a new, unrelated question.
          - "preference_note": when is_reply is True, a short instruction to
            prepend to the dispatched message — either naming the chosen
            dataset_id or telling the specialist to apply its dataset
            selection heuristics. None otherwise.

        Falls back to {"is_reply": False, "preference_note": None} on any
        parse error, so an unrecognized reply is treated as a fresh question.
        """
        ids = ", ".join(f"{label} ({did})" for label, did in dataset_choices)
        prompt = (
            "A user was asked to specify a dataset (or say they have no preference) "
            f"for this pending request: \"{pending_message}\"\n\n"
            f"Available datasets: {ids}\n\n"
            f"The user's next message is: \"{reply}\"\n\n"
            "Reply with JSON only:\n"
            "{\n"
            '  "is_reply": true | false,\n'
            '  "preference_note": "..." | null\n'
            "}\n\n"
            "Set is_reply=true if the message names a dataset/cohort from the list above, "
            "or says they have no preference / to pick the best one / etc.\n"
            "Set is_reply=false if it looks like a new, unrelated question.\n"
            "If is_reply=true, set preference_note to a short instruction for the specialist: "
            "either '[User dataset preference: <dataset_id>]' (using the matching dataset_id) "
            "or '[User has no dataset preference — apply your dataset selection heuristics.]'."
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"is_reply": False, "preference_note": None}

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

    def specialist_status_note(self, agent_id: str) -> str | None:
        """Check the specialist's HF Space runtime status via the HF API.

        Returns a short note to show the user if the Space isn't RUNNING
        (e.g. it's asleep and waking up), or None if it's running or the
        status couldn't be determined.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        hf_space = agent["hf_space"]
        try:
            resp = httpx.get(
                f"https://huggingface.co/api/spaces/{hf_space}/runtime",
                timeout=5,
            )
            stage = resp.json().get("stage")
        except Exception:
            return None
        if stage and stage != "RUNNING":
            return (
                f"_The specialist Space is currently `{stage}` — if it's "
                f"asleep (HF free tier), waking it up can take ~30-60s."
                f" Please be patient._"
            )
        return None

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
            gc = GradioClient(hf_space, httpx_kwargs={"timeout": SPECIALIST_TIMEOUT_SECONDS})
            # DecoupleRpy's interact_with_agent reads the query from a hidden gr.State.
            # Step 1: call /lambda to set that state for this session.
            gc.predict(x=message, api_name="/lambda")
            # Step 2: call /interact_with_agent with empty history — query comes from state.
            result = gc.predict(
                chatbot_history=[],
                api_name="/interact_with_agent",
            )

            # If the agent hit its step limit before producing a solution, keep
            # clicking "Continue" (via the /handle_continue endpoint the Gradio
            # UI's Continue button calls) until it produces a real solution.
            # Capped to avoid an infinite loop if the agent never converges.
            #
            # Note: a "Step limit reached" notice can appear *after* a Final
            # Solution in chatbot_history (the step that produced the solution
            # also happened to hit the limit). In that case `solution` is
            # already set, so don't call /handle_continue — doing so makes the
            # agent "continue" a task it already finished, producing a junk
            # acknowledgement (e.g. "standing by for your next request") that
            # would otherwise overwrite the real solution on the next pass.
            for _ in range(MAX_CONTINUES):
                solution, last_assistant, step_limit_hit = self._extract_response(result)
                if solution or not step_limit_hit:
                    break
                result = gc.predict(chatbot=result, api_name="/handle_continue")

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

    @staticmethod
    def _extract_response(chatbot_history: list) -> tuple[str | None, str | None, bool]:
        """Inspect a DecoupleRpy chatbot history for a final solution.

        Returns (solution, last_assistant_message, step_limit_hit).
        """
        if not isinstance(chatbot_history, list) or not chatbot_history:
            return None, None, False

        solution = None
        last_assistant = None
        step_limit_hit = False
        for msg in chatbot_history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content", "") or ""
            if not content.strip():
                continue
            # Skip the HF log-link notice
            if "Full run log saved" in content or "huggingface.co/datasets" in content:
                continue
            if "Step limit reached" in content:
                step_limit_hit = True
                continue
            last_assistant = content
            step_limit_hit = False
            if "Final Solution" in content or "solution-content" in content:
                solution = content
        return solution, last_assistant, step_limit_hit

    def agent_display_name(self, agent_id: str) -> str:
        agent = self._agents.get(agent_id, {})
        return agent.get("name", agent_id)
