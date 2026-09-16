from __future__ import annotations

from ..database import database, seed_demo_employees


def main() -> None:
    created = seed_demo_employees(database)
    print(f"Demo seed complete: {created} employee(s) created.")


if __name__ == "__main__":
    main()

