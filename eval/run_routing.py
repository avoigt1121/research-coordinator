"""Coordinator-level routing regression — asserts router.classify() decisions.

Unlike run_eval.py (which dispatches to the specialist and LLM-judges the
response), this harness exercises ONLY the routing decision: for each case it
calls router.classify() and checks the returned `route` (and `agent_id` for
specialist routes) against the expected value. Cheap and deterministic in what
it asserts — one classify call per case, no specialist round-trip, no judge.

Usage:
    python3 eval/run_routing.py                      # default bank
    python3 eval/run_routing.py eval/routing_cases.json

Exit code is non-zero if any case routes wrong, so it can gate a push.
Requires ANTHROPIC_API_KEY (or Anthropic_API_KEY) in research-coordinator/.env.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from router import ResearchRouter  # noqa: E402


def main() -> int:
    bank_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "routing_cases.json"
    with open(bank_path) as f:
        bank = json.load(f)

    router = ResearchRouter()
    cases = bank["cases"]
    failures = []

    print(f"Routing regression: {bank['metadata']['name']} ({len(cases)} cases)\n")
    for c in cases:
        result = router.classify(c["question"])
        route = result.get("route")
        agent_id = result.get("agent_id")

        route_ok = route == c["expected_route"]
        # agent_id only matters for specialist routes
        agent_ok = (
            agent_id == c["expected_agent_id"]
            if c["expected_route"] == "specialist"
            else True
        )
        passed = route_ok and agent_ok

        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {c['id']}: {c['question']}")
        if not passed:
            print(
                f"         expected route={c['expected_route']} "
                f"agent_id={c['expected_agent_id']}, "
                f"got route={route} agent_id={agent_id} "
                f"(reasoning: {result.get('reasoning')})"
            )
            failures.append(c["id"])

    total = len(cases)
    print(f"\n{total - len(failures)}/{total} routed correctly.")
    if failures:
        print(f"FAILURES: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
