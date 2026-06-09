# Eval Harness — Research Coordinator

## Scope (current bank)

The question bank in `pilot_questions.json` (sampled from
`decoupleRpy_agent_test_questions.json`) is **scoped to the DecoupleRpy
specialist only**. Every question is expected to:

1. Route through the coordinator to the `decouplerpy` specialist agent
   (routing correctness), and
2. Receive a response matching its `expected_behavior` tag — `EXECUTE`,
   `INFER_DATASET`, `FLAG_LIMITATION`, `REFUSE_NO_DATA`, or
   `REFUSE_OUT_OF_SCOPE` (response quality).

These two dimensions are graded separately:

- **Routing correctness** is computed automatically (no LLM call) — it's a
  simple check that `route == "specialist"` and `agent_id == "decouplerpy"`.
- **Response quality** is graded by an LLM judge (Claude) against the
  `expected_behavior` + `notes` fields from the question bank.

**Out of scope for this bank:** direct-response routing (conceptual
questions Claude should answer itself), multi-specialist routing (once a
second specialist agent exists), and coordinator-level conversational
framing. These need their own question banks once they're relevant —
do not extend this bank to cover them, to avoid diluting what it's
testing for.

## Running

```bash
# (re)generate the pilot sample from the full question bank
python3 eval/select_pilot.py

# run the pilot against the live coordinator + specialist
python3 eval/run_eval.py eval/pilot_questions.json
```

Requires a working `ANTHROPIC_API_KEY` (or `Anthropic_API_KEY`) in
`research-coordinator/.env` with available credit — used for both routing
classification and the LLM judge.

## Outputs

Each run writes three files to `eval/results/<timestamp>_*`:

- `_raw.json` — routing decisions, raw specialist/direct responses, latency
- `_graded.json` — raw + judge verdict (`PASS`/`FAIL`/`PARTIAL`) + reason
- `_report.md` — human-readable summary, with routing failures called out
  separately from quality failures

## Status

**Blocked**: as of 2026-06-09, the Anthropic API key in `.env` returns
"credit balance too low" on the first call. Add credits at
console.anthropic.com before running.

## Next steps (after pilot validates the harness)

- Run the full 109-question bank (`decoupleRpy_agent_test_questions.json`)
- Build a separate bank for coordinator-level routing (direct vs.
  specialist, multi-specialist dispatch) once relevant
- Consider a baseline-diff mode: save a graded run as a baseline, and have
  future runs flag verdict *changes* rather than re-grading from scratch
