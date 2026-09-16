from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..models import RuleConfig


RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "rules.json"


def _rule_document() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def load_rule_config() -> RuleConfig:
    payload = _rule_document()["config"]
    payload["max_time_seconds"] = float(
        os.getenv("SOLVER_MAX_TIME_SECONDS", str(payload["max_time_seconds"]))
    )
    payload["random_seed"] = int(
        os.getenv("SOLVER_RANDOM_SEED", str(payload["random_seed"]))
    )
    return RuleConfig.model_validate(payload)


def public_rules(config: RuleConfig | None = None) -> list[dict[str, Any]]:
    _ = config or load_rule_config()
    return [
        {
            **item,
            "rule_id": item["id"],
            "kind": item["category"],
            "title": item["name"],
            "enabled": True,
        }
        for item in _rule_document()["definitions"]
    ]
