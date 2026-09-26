# Evidence and run-record format

Every model or grounding run must be reproducible from its record. Store raw
outputs separately from summaries and never use a narrative summary as the
only evidence.

## Required run record

```json
{
  "run_id": "run-YYYYMMDD-NNN",
  "decision_id": "DD-1",
  "candidate": "provider/model",
  "model_version": "provider-version",
  "prompt_version": "phase0-v0",
  "started_at_utc": "2026-09-26T00:00:00Z",
  "cases": 30,
  "latency_ms": {"p50": 0, "p95": 0},
  "tokens": {"input": 0, "output": 0},
  "cost_usd": 0.0,
  "result_path": "artifacts/runs/dd-1/run-YYYYMMDD-NNN.jsonl",
  "reviewer": "",
  "notes": ""
}
```

Raw JSONL output must retain case IDs, literal prompts/inputs where permitted,
literal model output, parser status, and pass/fail rationale. Secrets must never
be recorded.
