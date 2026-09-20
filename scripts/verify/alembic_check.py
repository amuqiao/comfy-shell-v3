from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT_DIR = Path(__file__).resolve().parents[2]


def main() -> int:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"alembic must have exactly one head, got: {heads}")
    print(f"OK alembic-head head={heads[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

