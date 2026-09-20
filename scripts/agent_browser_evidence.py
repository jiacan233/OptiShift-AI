"""Read-only evidence helpers for the opt-in real browser acceptance suite."""
from __future__ import annotations

import argparse
from pathlib import Path

from agent_multiturn_live import snapshot, source_fingerprint, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("manifest", "snapshot"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if args.mode == "snapshot":
        if args.database is None:
            parser.error("snapshot requires --database")
        value = snapshot(args.database)
    else:
        value = {
            **source_fingerprint(),
            "suite": "opt-in real browser multi-turn acceptance",
            "database": "SQLite baseline copied before each case; no later fixture writes",
            "provider": "existing .env; LLM_ENABLED=true; observed real _post calls",
            "scope": ["B refresh", "G correction", "H immutable cards", "J restore", "draft gate/cancel/chat confirmation"],
            "timing": "browser elapsed is send/click through persisted terminal and input ready; nested backend stages must not be summed",
        }
    write_json(args.output, value)


if __name__ == "__main__":
    main()
