"""Validated runtime limits. Invalid values always fall back to safe defaults."""

import math
import os


def positive_seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value > 0 else default
    except (ValueError, TypeError):
        return default


def llm_read_timeout_seconds() -> float:
    """Shared Provider read/wall budget for all Agent LLM stages."""
    return positive_seconds("LLM_READ_TIMEOUT_SECONDS", 120)
