"""Seed idempotency test — run ``scripts.seed_colsubsidio`` twice and assert
the catalogue/afiliado counts and the sparse-row invariant.

Sketches the seed-and-bootstrap spec scenarios:
  * seed_colsubsidio inserts 44 proyectos verbatim (sparse rows preserved);
  * re-running the seed is idempotent (proyectos stay 44, not 88; afiliado
    seed set is replaced via DELETE WHERE is_seed=true so seed_total stays 15);
  * ABETO and LA ARBOLEDA each appear exactly once (the blank-``modelo`` ->
    ``''`` NOT NULL DEFAULT '' decision keeps the natural key functional).

Skips cleanly when no Postgres is reachable (the seed needs the catalogue
tables created by ``scripts/bootstrap_db.py``).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.db import AsyncSessionLocal, engine

# Import the seed module by file path so the test does not depend on
# ``scripts`` being importable as a package from the pytest root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_spec = importlib.util.spec_from_file_location(
    "seed_colsubsidio", _PROJECT_ROOT / "scripts" / "seed_colsubsidio.py"
)
assert _spec is not None and _spec.loader is not None
seed_colsubsidio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_colsubsidio)


async def _db_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except (OperationalError, OSError):  # noqa: PERF203
        return False


# Module-scope skip gate computed once at collection time. The test still
# re-checks reachability per test (the DB may drop between tests in CI).
_DB_UP: bool = asyncio.run(_db_reachable())
pytestmark = pytest.mark.skipif(
    not _DB_UP or os.environ.get("VIVI_SKIP_DB_TESTS") == "1",
    reason="Postgres not reachable (set VIVI_SKIP_DB_TESTS=1 to force-skip)",
)


async def _counts() -> tuple[int, int, int, int]:
    async with AsyncSessionLocal() as session:
        p_total = (
            await session.execute(text("select count(*) from proyectos_colsubsidio"))
        ).scalar_one()
        a_seed = (
            await session.execute(
                text("select count(*) from afiliados_colsubsidio where is_seed = true")
            )
        ).scalar_one()
        abeto = (
            await session.execute(
                text("select count(*) from proyectos_colsubsidio where proyecto = 'ABETO'")
            )
        ).scalar_one()
        arboleda = (
            await session.execute(
                text("select count(*) from proyectos_colsubsidio where proyecto = 'LA ARBOLEDA'")
            )
        ).scalar_one()
    return int(p_total), int(a_seed), int(abeto), int(arboleda)


@pytest.mark.asyncio
async def test_seed_is_idempotent_run_twice() -> None:
    """Run the seed twice; counts must hold and sparse rows must stay singletons."""
    # First run (tables are assumed bootstrap'd by the operator / fixture).
    code1 = await seed_colsubsidio._run()
    assert code1 == 0, "first seed run failed"
    p1, a1, ab1, ar1 = await _counts()

    # Second run — must NOT duplicate proyectos (44, not 88) and must replace
    # the afiliado seed set (15, not 30).
    code2 = await seed_colsubsidio._run()
    assert code2 == 0, "second seed run failed"
    p2, a2, ab2, ar2 = await _counts()

    assert p1 == 44 and p2 == 44, f"proyectos must be 44 on both runs: {p1},{p2}"
    assert a1 == 15 and a2 == 15, f"afiliado seed must be 15 on both runs: {a1},{a2}"
    # ABETO and LA ARBOLEDA carry blank modelo -> stored as '' under NOT NULL
    # DEFAULT ''; the (proyecto, modelo) unique key catches them on the re-seed
    # so each appears exactly once even after the second run.
    assert ab1 == 1 and ab2 == 1, f"ABETO must appear exactly once: {ab1},{ab2}"
    assert ar1 == 1 and ar2 == 1, f"LA ARBOLEDA must appear exactly once: {ar1},{ar2}"


@pytest.mark.asyncio
async def test_seed_preserves_verbatim_quirks() -> None:
    """After a seed run the catalogue quirks are present verbatim."""
    await seed_colsubsidio._run()
    async with AsyncSessionLocal() as session:
        vibo = (
            await session.execute(
                text(
                    "select tipo, municipio, modelo from proyectos_colsubsidio "
                    "where proyecto='VIBO ONCE' and modelo='B2'"
                )
            )
        ).one()
        assert tuple(vibo) == ("VIS", "VIS", "B2"), (
            "VIBO ONCE B2 must keep tipo=municipio='VIS' verbatim"
        )

        vers_e = (
            await session.execute(
                text(
                    "select area_construida_m2, area_privada_m2 from proyectos_colsubsidio "
                    "where proyecto='VERSALLES' and modelo='E'"
                )
            )
        ).one()
        assert float(vers_e[0]) == 56.29 and float(vers_e[1]) == 60.60, (
            "VERSALLES E: area_privada (60,60) must exceed construida (56,29) verbatim"
        )
        assert float(vers_e[1]) > float(vers_e[0]), "the privada>construida quirk must hold"

        nogales = (
            await session.execute(
                text("select valor_vis_smmlv from proyectos_colsubsidio where proyecto='LOS NOGALES'")
            )
        ).scalar_one()
        assert nogales is None, "LOS NOGALES has no Valor VIS in the source -> NULL"

        abeto = (
            await session.execute(
                text(
                    "select modelo, direccion, area_privada_m2 from proyectos_colsubsidio "
                    "where proyecto='ABETO'"
                )
            )
        ).one()
        assert abeto[0] == "" and abeto[1] is None and abeto[2] is None, (
            "ABETO: blank modelo -> '', blank direccion/area_privada -> NULL"
        )


@pytest.mark.asyncio
async def test_seed_afiliado_distribution() -> None:
    """The 15 fabricated afiliados cover every categoria and credit band."""
    await seed_colsubsidio._run()
    async with AsyncSessionLocal() as session:
        cats = {
            r[0]
            for r in (
                await session.execute(
                    text(
                        "select distinct categoria_afiliado from afiliados_colsubsidio "
                        "where is_seed=true order by categoria_afiliado"
                    )
                )
            ).all()
        }
        assert cats == {"A", "B", "C"}, f"afiliado categorias not all covered: {cats}"

        subsidio_true = (
            await session.execute(
                text(
                    "select count(*) from afiliados_colsubsidio "
                    "where is_seed=true and ha_recibido_subsidio=true"
                )
            )
        ).scalar_one()
        assert subsidio_true >= 1, "at least one seed afiliado must have ha_recibido_subsidio=true"

        # The six credit bands (150-499, 500-649, 650-699, 700-749, 750-799,
        # 800-950) each need at least one seed afiliado.
        bands = [
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 150 and 499"
                    )
                )
            ).scalar_one(),
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 500 and 649"
                    )
                )
            ).scalar_one(),
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 650 and 699"
                    )
                )
            ).scalar_one(),
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 700 and 749"
                    )
                )
            ).scalar_one(),
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 750 and 799"
                    )
                )
            ).scalar_one(),
            (
                await session.execute(
                    text(
                        "select count(*) from afiliados_colsubsidio where is_seed=true "
                        "and score_credito between 800 and 950"
                    )
                )
            ).scalar_one(),
        ]
        assert all(int(b) >= 1 for b in bands), (
            f"each of the six credit bands must have >=1 seed afiliado: {bands}"
        )

        # Demo stars present and reproducible.
        for cedula, cat, score in [("1010101010", "A", 880), ("2020202020", "B", 720), ("3030303030", "C", 580)]:
            row = (
                await session.execute(
                    text(
                        "select categoria_afiliado, score_credito from afiliados_colsubsidio "
                        "where tipo_documento='CC' and numero_documento=:c and is_seed=true"
                    ),
                    {"c": cedula},
                )
            ).one_or_none()
            assert row is not None, f"demo star cedula {cedula} missing"
            assert row[0] == cat and int(row[1]) == score, (
                f"demo star {cedula} mismatch: {tuple(row)}"
            )