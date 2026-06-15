"""
Routes user messages to either:
  - Direct Claude API response (fast, conceptual questions)
  - Specialist agent via gradio_client (computation questions)
"""
from __future__ import annotations

import json
import os
import re
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

# Number of times dispatch_to_specialist will retry the /lambda +
# /interact_with_agent dispatch with a fresh session if the agent's reply
# doesn't echo the dispatched query back (see _echoed_query) — guards
# against an intermittent gr.State race between the two calls.
MAX_DISPATCH_RETRIES = 2

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
        hf_space = self._resolve_hf_space(agent)
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

    def _resolve_hf_space(self, agent: dict) -> str:
        """Resolve a specialist's target HF Space, allowing a per-agent env override.

        Default is the prod value from agents.yaml (so promoting `dev` -> `main`
        never changes the prod target). A dev deployment can point at a dev Space
        by setting env var `HF_SPACE_<ID>` (id upper-cased), e.g. on the
        research_coordinator_dev Space:
            HF_SPACE_DECOUPLERPY=anne-voigt/Paper2Agent_decoupleRpy_dev
        This keeps dev/prod routing in env config, not in branch-divergent code.
        """
        override = os.environ.get(f"HF_SPACE_{agent['id'].upper()}")
        return override or agent["hf_space"]

    def dispatch_to_specialist(self, agent_id: str, message: str, dataset_constraint: list | None = None,
                                return_trace: bool = False):
        """Send message to specialist HF Space via gradio_client and return result.

        Phase 1: real dispatch is implemented; the Space may be cold so we
        wrap in try/except and return a helpful stub on failure.

        By default returns just the final solution string (what the user sees).
        If `return_trace=True`, returns a `(solution, trace_digest)` tuple where
        `trace_digest` is a compact summary of the agent's actual tool-execution
        steps (code-output observations + tool names), extracted from the full
        chatbot history the Space returns. This trace is pure post-processing of
        data already on the wire — it is NOT fed back into the specialist's LLM
        context, so it adds no token cost or latency to the agent run. It lets a
        caller (e.g. the eval judge) verify that numbers in the solution came
        from real computation rather than inferring fabrication from the prose
        alone.
        """
        # Backward-compatible blocking API: drain the streaming generator and
        # return only the final frame. Non-UI callers (the eval harness) use
        # this; the Gradio UI calls dispatch_to_specialist_stream directly to
        # render the agent's steps live.
        final_text, final_trace = "", ""
        for text, trace, _done in self.dispatch_to_specialist_stream(
            agent_id, message, dataset_constraint=dataset_constraint
        ):
            final_text, final_trace = text, trace
        return (final_text, final_trace) if return_trace else final_text

    def dispatch_to_specialist_stream(self, agent_id: str, message: str,
                                       dataset_constraint: list | None = None):
        """Generator yielding (display_text, trace_digest, done) frames as the
        specialist streams its workflow steps live.

        The specialist's /interact_with_agent is a Gradio *generator* endpoint
        (it yields a gr.ChatMessage per LangGraph step), so we submit() it and
        iterate the returned Job — gradio_client's Job.__next__ surfaces each
        intermediate output as it lands on the wire. This adds NO latency vs the
        old predict() path: those step frames were always being transmitted;
        predict() simply discarded every frame but the last. Here we render each
        as live progress, then emit the polished solution as the final
        (done=True) frame.

        Frames:
          - (progress_markdown, trace_digest, False) for each streamed step
          - (solution_or_fallback, final_trace, True) exactly once, at the end
        On any error a single (error_message, "", True) frame is yielded.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            yield (f"[Error] Unknown agent: {agent_id}", "", True)
            return

        hf_space = self._resolve_hf_space(agent)

        # Optional HF token (see dispatch_to_specialist): prod's specialist is
        # public so we omit the auth kwarg; gradio_client's kwarg is `token`,
        # passed only when HF_TOKEN is actually set (e.g. a private dev Space).
        hf_token = os.environ.get("HF_TOKEN") or None
        client_kwargs: dict = {"httpx_kwargs": {"timeout": SPECIALIST_TIMEOUT_SECONDS}}
        if hf_token:
            client_kwargs["token"] = hf_token

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
            yield (
                f"[Stub] gradio_client is not installed. "
                f"Would dispatch to {agent['name']} ({hf_space}) with: {message}",
                "", True,
            )
            return

        try:
            # DecoupleRpy's interact_with_agent reads the query from a hidden
            # gr.State set by a separate /lambda call. This two-step dispatch
            # occasionally races: /interact_with_agent can read the state before
            # /lambda's write commits, so the agent sees an empty query and
            # replies generically. Detect that and retry with a fresh session
            # (new gradio_client = new session_hash) before giving up.
            result = None
            gc = None
            for _attempt in range(MAX_DISPATCH_RETRIES):
                gc = GradioClient(hf_space, **client_kwargs)
                # Step 1: stash the query in gr.State for this session.
                gc.predict(x=message, api_name="/lambda")
                # Step 2: submit (not predict) so we can iterate intermediate
                # frames as the agent streams its steps.
                job = gc.submit(chatbot_history=[], api_name="/interact_with_agent")
                result = None
                for frame in job:
                    result = frame
                    yield (self._render_progress(frame),
                           self._extract_execution_trace(frame), False)
                if result is None:
                    result = job.result()
                if self._echoed_query(result, message):
                    break

            # If the agent hit its step limit before producing a solution, keep
            # clicking "Continue" (via /handle_continue) until it produces a
            # real solution — also streamed. Capped against non-convergence.
            #
            # Note: a "Step limit reached" notice can appear *after* a Final
            # Solution (the solution-producing step also hit the limit). In that
            # case `solution` is already set, so don't continue — doing so makes
            # the agent "continue" a finished task and overwrite the real answer.
            for _ in range(MAX_CONTINUES):
                solution, last_assistant, step_limit_hit = self._extract_response(result)
                if solution or not step_limit_hit:
                    break
                job = gc.submit(chatbot=result, api_name="/handle_continue")
                cont = None
                for frame in job:
                    cont = frame
                    yield (self._render_progress(frame),
                           self._extract_execution_trace(frame), False)
                result = cont if cont is not None else job.result()

            solution, last_assistant, _ = self._extract_response(result)
            final = solution or last_assistant or str(result)
            yield (final, self._extract_execution_trace(result), True)
        except Exception as exc:
            yield (
                f"[{agent['name']}] The specialist agent could not be reached "
                f"(Space may be cold or loading). Error: {exc}\n\n"
                "Please try again in a moment, or rephrase your question for a direct answer.",
                "", True,
            )

    @staticmethod
    def _echoed_query(chatbot_history: list, message: str) -> bool:
        """Check whether chatbot_history's first (user) turn matches `message`.

        Guards against an intermittent gr.State race between /lambda (which
        stashes the query) and /interact_with_agent (which reads it) — if the
        state read happens before the write commits, the agent sees an empty
        query and responds with a generic "no instruction received" message.
        """
        if not isinstance(chatbot_history, list) or not chatbot_history:
            return False
        first = chatbot_history[0]
        if not isinstance(first, dict) or first.get("role") != "user":
            return False
        return first.get("content", "").strip() == message.strip()

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

    @staticmethod
    def _render_progress(chatbot_history: list, max_chars: int = 1500) -> str:
        """Render a live 'agent is working' view from a partial chatbot history.

        Shows the most recent meaningful assistant step (HTML stripped) so the
        coordinator chat reflects what the specialist is doing right now. The
        full step-by-step evidence accumulates separately in the "What
        happened?" panel via _extract_execution_trace.
        """
        latest = ""
        if isinstance(chatbot_history, list):
            for msg in chatbot_history:
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = (msg.get("content") or "").strip()
                if not content:
                    continue
                if "Full run log saved" in content or "huggingface.co/datasets" in content:
                    continue
                latest = content
        text = re.sub(r"<[^>]+>", "", latest)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > max_chars:
            text = "…" + text[-max_chars:]
        return text or "_…thinking…_"

    @staticmethod
    def _extract_execution_trace(chatbot_history: list, max_chars: int = 6000) -> str:
        """Build a compact digest of the agent's real tool-execution steps.

        Pulls the "Code Output" execution-result blocks (the actual tool/code
        outputs the agent observed) and the tool/function calls out of the full
        chatbot history, stripping the HTML chrome the Gradio UI wraps them in.
        This is what lets a judge confirm whether numbers in the final solution
        came from real computation. The final-solution block itself is excluded
        (we want the *evidence*, not the narrative). Capped to `max_chars` to
        keep downstream prompts bounded; if truncated, keeps the most recent
        steps (closest to the reported solution).
        """
        if not isinstance(chatbot_history, list) or not chatbot_history:
            return ""

        def _strip_html(text: str) -> str:
            text = re.sub(r"<[^>]+>", "", text)
            return re.sub(r"\n{3,}", "\n\n", text).strip()

        blocks: list[str] = []
        for msg in chatbot_history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content", "") or ""
            if not content.strip():
                continue
            # Skip the final solution and the HF log-link notice — we want the
            # upstream execution evidence, not the polished answer.
            if "Final Solution" in content or "solution-content" in content:
                continue
            if "Full run log saved" in content or "huggingface.co/datasets" in content:
                continue
            cleaned = _strip_html(content)
            if not cleaned:
                continue
            # Keep the steps that carry real evidence: executed code and the
            # tool/code outputs the agent observed.
            if "Code Output" in cleaned or "Executing Code" in cleaned or "Execution Result" in cleaned:
                blocks.append(cleaned)

        digest = "\n\n---\n\n".join(blocks)
        if len(digest) > max_chars:
            # Keep the tail (most recent steps, nearest the reported numbers).
            digest = "...[earlier steps truncated]...\n\n" + digest[-max_chars:]
        return digest

    @staticmethod
    def flag_unbacked_numbers(response: str, execution_trace: str) -> bool:
        """Narrow, deterministic fabrication backstop (belt-and-suspenders).

        Returns True only in the egregious case: the response presents a
        substantial set of concrete numeric results but the execution trace
        shows NO real tool/code output to back them. Intentionally conservative
        so it does not trip on legitimate non-execution answers (out-of-scope
        refusals, request-for-required-input, conceptual answers, limitation
        flags) — those don't contain numeric results tables.
        """
        if not response:
            return False
        # Real tool output present → not unbacked.
        if execution_trace and ("Code Output" in execution_trace
                                 or "Execution Result" in execution_trace):
            return False
        # Count concrete decimal results. A high bar (>= 8) keeps refusals and
        # clarifications (which may mention an occasional "n=89" or a p-value in
        # prose) from being flagged; only a results-table-sized cluster trips it.
        floats = re.findall(r"-?\d+\.\d+", response)
        return len(floats) >= 8

    def agent_display_name(self, agent_id: str) -> str:
        agent = self._agents.get(agent_id, {})
        return agent.get("name", agent_id)
