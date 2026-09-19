"""Load only LLM settings from local .env, then run the isolated live harness."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
import pytest


def main():
    values = dotenv_values(Path(__file__).resolve().parents[2] / ".env", interpolate=False)
    for key, value in values.items():
        if key.startswith("LLM_") and value is not None:
            os.environ.setdefault(key, value)
    os.environ.setdefault("LIVE_AGENT_EVAL", "true")
    return pytest.main(
        ["tests/evals", "-v", "-rs", "--tb=short", *sys.argv[1:]]
    )


if __name__ == "__main__":
    raise SystemExit(main())
