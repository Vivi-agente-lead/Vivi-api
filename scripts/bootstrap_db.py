"""Idempotent schema bootstrap: create all tables if absent.

This is the contract path that ``init_db`` in ``app/main.py`` only approximates:
the FastAPI lifespan swallows ``create_all`` failures with a warning, so a
process can answer ``GET /health`` 200 with no tables. This script raises loudly
instead and returns a real exit code so an ordered run after a fresh wipe can
be asserted by the seed-and-bootstrap spec scenario "bootstrap then seed runs
in order".

Run as::

    python -m scripts.bootstrap_db
    # or directly:
    .venv/bin/python scripts/bootstrap_db.py

NEVER drops anything: ``create_all(checkfirst=True)`` only creates tables that
do not yet exist. Use ``scripts/reset_db.py`` for the destructive path.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import sys

# Project root on sys.path so ``import app`` resolves whether the script is
# run as ``python -m scripts.bootstrap_db`` or ``python scripts/bootstrap_db.py``.
_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.db import engine  # noqa: E402
from app.models import Base  # noqa: E402  (registers every entity on the metadata)

logger = logging.getLogger(__name__)


async def _create_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger.info("bootstrap_db.start")
    try:
        await _create_all()
    except Exception:
        logger.exception("bootstrap_db.failed")
        return 1
    logger.info("bootstrap_db.done — tables ensured (checkfirst=True)")
    return 0


def main() -> int:
    async def _run() -> int:
        try:
            code = await _main()
        finally:
            await engine.dispose()
        return code

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())