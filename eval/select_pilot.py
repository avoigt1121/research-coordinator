"""Select a stratified pilot sample from the full question bank.

Picks ~18 questions across all 5 categories, including the known
NOD-003 (Chan-Seng-Yue) trap and key OOS boundary cases, and writes
them to eval/pilot_questions.json for the eval harness to consume.
"""
import json
from pathlib import Path

SOURCE = Path("/Users/annivoigt/Documents/business/plans&documentation/decoupleRpy_agent_test_questions.json")
OUT = Path(__file__).parent / "pilot_questions.json"

PILOT_IDS = [
    # answerable_specified
    "ANS-001", "ANS-005", "ANS-009", "ANS-021",
    # answerable_infer_dataset
    "INF-001", "INF-005", "INF-007", "INF-016",
    # data_limitation
    "LIM-001", "LIM-004", "LIM-008", "LIM-017",
    # no_data_refuse
    "NOD-003", "NOD-005", "NOD-010",
    # out_of_scope_refuse
    "OOS-002", "OOS-009", "OOS-013",
]


def main():
    with open(SOURCE) as f:
        data = json.load(f)

    by_id = {q["id"]: q for q in data["questions"]}
    pilot = [by_id[qid] for qid in PILOT_IDS]

    missing = set(PILOT_IDS) - set(by_id)
    if missing:
        raise ValueError(f"IDs not found in source bank: {missing}")

    out = {
        "metadata": {
            "name": "Pilot subset of decoupleRpy Agent Evaluation Question Bank",
            "scope": (
                "DecoupleRpy specialist only. Every question is expected to "
                "route through the coordinator to the 'decouplerpy' specialist "
                "agent. Routing correctness (reaching DecoupleRpy) is graded "
                "automatically; response quality is graded by an LLM judge "
                "against expected_behavior. Broader multi-specialist or "
                "direct-response routing tests are out of scope for this bank."
            ),
            "source": str(SOURCE),
            "total_questions": len(pilot),
        },
        "questions": pilot,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(pilot)} pilot questions to {OUT}")


if __name__ == "__main__":
    main()
