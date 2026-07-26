"""Destructive schema reset — drops ALL registered tables. Requires ``--yes``.

NEVER invoked by the server (nor by ``bootstrap_db``, nor the FastAPI lifespan,
nor ``seed_colsubsidio``). Use this after a schema change to regenerate the
``leads`` / ``afiliados_colsubsidio`` / ``proyectos_colsubsidio`` tables.

Procedure (run from the project root, with the project ``.venv`` on PATH)::

    .venv/bin/python scripts/reset_db.py --yes
    .venv/bin/python scripts/bootstrap_db.py
    .venv/bin/python scripts/seed_colsubsidio.py

A destructive path gated only on ``app_env == "development"`` MUST NOT be used:
``development`` is the shipped default in ``.env.example``, ``docker-compose.yml``
and the ``Settings`` field, so such a gate would wipe the auditable artifact on
every restart. That is why this script demands an explicit ``--yes`` flag.

Run as::

    python -m scripts.reset_db --yes
    .venv/bin/python scripts/reset_db.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.db import engine  # noqa: E402
from app.models import Base  # noqa: E402

logger = logging.getLogger(__name__)


async def _drop_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _run_drop() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger.info("reset_db.start — dropping all tables")
    try:
        await _drop_all()
    except Exception:
        logger.exception("reset_db.failed")
        return 1
    logger.info("reset_db.done — all tables dropped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required confirmation flag — refuses to run without it",
    )
    args = parser.parse_args()
    if not args.yes:
        print("reset_db is destructive; pass --yes to confirm.", file=sys.stderr)
        return 2

    async def _run() -> int:
        try:
            code = await _run_drop()
        finally:
            await engine.dispose()
        return code

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())