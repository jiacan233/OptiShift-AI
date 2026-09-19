import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def evaluation_output_dir():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = Path(os.getenv("LLM_EVAL_OUTPUT_DIR") or f"artifacts/agent-evals/{stamp}")
    path.mkdir(parents=True, exist_ok=True)
    yield path
    records = [json.loads(p.read_text(encoding="utf-8")) for p in path.glob("case-*.json")]
    executed = [r for r in records if r["status"] != "skipped"]
    passed = sum(r["status"] == "passed" for r in records)
    latencies = [r["router_latency_ms"] for r in executed if r.get("router_latency_ms") is not None]
    summary = {
        "total": len(records), "passed": passed,
        "failed": sum(r["status"] == "failed" for r in records),
        "skipped": sum(r["status"] == "skipped" for r in records),
        "success_rate": passed / len(executed) if executed else None,
        "average_router_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "max_router_latency_ms": max(latencies, default=0),
        "fallback_count": sum(bool(r.get("fallback_used")) for r in executed),
        "max_schema_bytes": max((r.get("schema_bytes", 0) for r in executed), default=0),
        "cases": [{k: r.get(k) for k in ("name", "status", "model", "router_latency_ms", "duration_seconds", "fallback_used", "failures")} for r in records],
    }
    (path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
