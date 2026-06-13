"""Run the research-coordinator + DecoupleRpy specialist against an eval
question bank, then grade each response with an LLM judge.

Usage:
    python3 eval/run_eval.py eval/pilot_questions.json

Outputs:
    eval/results/<timestamp>_raw.json     -- routing + raw responses + latency
    eval/results/<timestamp>_graded.json  -- raw + judge verdict/reason
    eval/results/<timestamp>_report.md    -- human-readable summary
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from router import ResearchRouter  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

JUDGE_MODEL = "claude-sonnet-4-6"

# This question bank is scoped to the DecoupleRpy specialist only — every
# question should route to "specialist" with this agent_id. Routing
# correctness (did it reach DecoupleRpy at all?) is graded automatically,
# separate from the LLM judge's response-quality verdict.
EXPECTED_AGENT_ID = "decouplerpy"

JUDGE_RUBRIC = """\
You are grading the DecoupleRpy specialist agent's response within a PDAC
research agent system. Routing correctness (whether this question reached
DecoupleRpy at all) has already been checked separately — your job is ONLY
to grade the content/quality of the response against the expected behavior.
Grade strictly but fairly.

Question: {question}

Expected behavior category: {expected_behavior}
Grading notes: {notes}

For context, this question was routed to: {route_taken}
{route_detail}

--- AGENT RESPONSE ---
{response}
--- END RESPONSE ---

Rubric by expected_behavior:
- EXECUTE: The agent should have actually run the requested analysis and
  returned concrete results (numbers, tables, named TFs/pathways) — not just
  a description of what it would do.
- INFER_DATASET: The agent should pick a reasonable dataset for the question,
  briefly justify the choice, and proceed (or offer to proceed) with the analysis.
- FLAG_LIMITATION: The agent should identify the specific data limitation
  described in the grading notes and redirect or adjust rather than silently
  producing results that ignore the limitation.
- REFUSE_NO_DATA: The agent should clearly state the requested data/cohort is
  not available in the registry, without fabricating results. A redirect to
  an available alternative (if one exists) is a bonus, not required.
- REFUSE_OUT_OF_SCOPE: The agent should decline or redirect the out-of-scope
  request. A "redirect with explanation of decoupleR's role" counts as a PASS
  per the grading notes, even if not a hard refusal.

Respond with ONLY a JSON object (no markdown fences):
{{"verdict": "PASS" | "FAIL" | "PARTIAL", "reason": "<one or two sentences>"}}
"""


def run_question(router: ResearchRouter, q: dict) -> dict:
    question = q["question"]
    t0 = time.monotonic()

    classification = router.classify(question)
    route = classification.get("route", "direct")
    agent_id = classification.get("agent_id")
    reasoning = classification.get("reasoning", "")

    if route == "specialist" and agent_id:
        response_text = router.dispatch_to_specialist(agent_id, question)
        route_detail = f"Specialist: {router.agent_display_name(agent_id)}. Routing reasoning: {reasoning}"
    else:
        chunks = list(router.direct_response(question, []))
        response_text = "".join(chunks)
        route_detail = f"Direct response. Routing reasoning: {reasoning}"

    latency = time.monotonic() - t0

    routing_correct = (route == "specialist" and agent_id == EXPECTED_AGENT_ID)

    return {
        "id": q["id"],
        "category": q["category"],
        "question": question,
        "expected_behavior": q["expected_behavior"],
        "notes": q.get("notes", ""),
        "route_taken": route,
        "agent_id": agent_id,
        "routing_correct": routing_correct,
        "routing_reasoning": reasoning,
        "route_detail": route_detail,
        "response": response_text,
        "latency_seconds": round(latency, 1),
    }


def judge_result(router: ResearchRouter, result: dict) -> dict:
    prompt = JUDGE_RUBRIC.format(
        question=result["question"],
        expected_behavior=result["expected_behavior"],
        notes=result["notes"],
        route_taken=result["route_taken"],
        route_detail=result["route_detail"],
        response=result["response"][:6000],  # cap to keep judge prompt bounded
    )
    response = router._client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        verdict = {"verdict": "PARTIAL", "reason": f"Judge parse error. Raw: {raw[:200]}"}
    return {**result, "judge_verdict": verdict.get("verdict", "PARTIAL"), "judge_reason": verdict.get("reason", "")}


def write_report(graded: list[dict], path: Path):
    lines = [
        "# Eval Report",
        "",
        f"**Scope: DecoupleRpy specialist only.** Every question in this bank is "
        f"expected to route to `{EXPECTED_AGENT_ID}`. Routing correctness "
        f"(coordinator → DecoupleRpy) is graded automatically; response quality "
        f"is graded by an LLM judge against `expected_behavior`. "
        f"Broader multi-specialist / direct-response routing tests are out of "
        f"scope for this bank and will be added separately.",
        "",
    ]

    counts = {"PASS": 0, "FAIL": 0, "PARTIAL": 0}
    for r in graded:
        counts[r["judge_verdict"]] = counts.get(r["judge_verdict"], 0) + 1
    total = len(graded)
    routing_failures = [r for r in graded if not r["routing_correct"]]

    lines.append(f"**Total: {total}** — Quality: PASS {counts.get('PASS', 0)}, "
                  f"PARTIAL {counts.get('PARTIAL', 0)}, FAIL {counts.get('FAIL', 0)} "
                  f"| Routing: {total - len(routing_failures)}/{total} correct")

    latencies = [r["latency_seconds"] for r in graded]
    total_seconds = sum(latencies)
    avg_seconds = total_seconds / total if total else 0
    lines.append(f"**Latency:** total {total_seconds / 60:.1f} min, "
                  f"avg {avg_seconds:.1f}s, min {min(latencies):.1f}s, "
                  f"max {max(latencies):.1f}s")
    lines.append("")

    if routing_failures:
        lines.append("## ⚠️ Routing failures (did not reach DecoupleRpy)")
        for r in routing_failures:
            lines.append(f"- **{r['id']}**: routed to `{r['route_taken']}`"
                          + (f" / `{r['agent_id']}`" if r["agent_id"] else "")
                          + f" — reasoning: {r['routing_reasoning']}")
        lines.append("")

    for r in graded:
        emoji = {"PASS": "✅", "FAIL": "❌", "PARTIAL": "⚠️"}.get(r["judge_verdict"], "?")
        routing_mark = "✅" if r["routing_correct"] else "❌"
        lines.append(f"## {emoji} {r['id']} — {r['category']} ({r['expected_behavior']})")
        lines.append(f"**Question:** {r['question']}")
        lines.append(f"**Routing:** {routing_mark} {r['route_taken']}"
                      + (f" → {r['agent_id']}" if r["agent_id"] else ""))
        lines.append(f"**Latency:** {r['latency_seconds']}s")
        lines.append(f"**Quality:** {r['judge_verdict']} — {r['judge_reason']}")
        lines.append("")
        lines.append("<details><summary>Response</summary>")
        lines.append("")
        lines.append("```")
        lines.append(r["response"][:3000])
        lines.append("```")
        lines.append("</details>")
        lines.append("")

    path.write_text("\n".join(lines))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 eval/run_eval.py <questions.json>")
        sys.exit(1)

    questions_path = Path(sys.argv[1])
    with open(questions_path) as f:
        bank = json.load(f)

    router = ResearchRouter()

    # Checkpoint file is keyed on the question bank name so a crashed run
    # can be resumed without re-paying for already-completed questions.
    checkpoint_path = RESULTS_DIR / f"_checkpoint_{questions_path.stem}_raw.json"
    raw_results = []
    completed_ids = set()
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            raw_results = json.load(f)
        completed_ids = {r["id"] for r in raw_results}
        print(f"Resuming from checkpoint: {len(raw_results)} question(s) already completed")

    for i, q in enumerate(bank["questions"], 1):
        if q["id"] in completed_ids:
            print(f"[{i}/{len(bank['questions'])}] {q['id']}: skipped (already in checkpoint)")
            continue
        print(f"[{i}/{len(bank['questions'])}] {q['id']}: {q['question'][:70]}...")
        result = run_question(router, q)
        print(f"    -> route={result['route_taken']} agent={result['agent_id']} "
              f"latency={result['latency_seconds']}s")
        raw_results.append(result)
        with open(checkpoint_path, "w") as f:
            json.dump(raw_results, f, indent=2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RESULTS_DIR / f"{timestamp}_raw.json"
    with open(raw_path, "w") as f:
        json.dump(raw_results, f, indent=2)
    print(f"\nWrote raw results to {raw_path}")

    # Grading checkpoint, same idea — the judge calls are cheap individually
    # but a crash partway through grading shouldn't force re-grading everything.
    graded_checkpoint_path = RESULTS_DIR / f"_checkpoint_{questions_path.stem}_graded.json"
    graded_results = []
    graded_ids = set()
    if graded_checkpoint_path.exists():
        with open(graded_checkpoint_path) as f:
            graded_results = json.load(f)
        graded_ids = {r["id"] for r in graded_results}
        print(f"Resuming grading from checkpoint: {len(graded_results)} question(s) already graded")

    print("\nGrading with LLM judge...")
    for i, r in enumerate(raw_results, 1):
        if r["id"] in graded_ids:
            print(f"[{i}/{len(raw_results)}] {r['id']}: skipped (already graded)")
            continue
        print(f"[{i}/{len(raw_results)}] Judging {r['id']}...")
        graded_results.append(judge_result(router, r))
        with open(graded_checkpoint_path, "w") as f:
            json.dump(graded_results, f, indent=2)

    graded_path = RESULTS_DIR / f"{timestamp}_graded.json"
    with open(graded_path, "w") as f:
        json.dump(graded_results, f, indent=2)
    print(f"Wrote graded results to {graded_path}")

    report_path = RESULTS_DIR / f"{timestamp}_report.md"
    write_report(graded_results, report_path)
    print(f"Wrote report to {report_path}")

    # Clean up checkpoints now that the run completed successfully.
    checkpoint_path.unlink(missing_ok=True)
    graded_checkpoint_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
