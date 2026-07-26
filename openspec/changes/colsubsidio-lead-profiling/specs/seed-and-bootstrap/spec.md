# Delta for seed-and-bootstrap

## ADDED Requirements

### Requirement: Idempotent DB Bootstrap and Colsubsidio Seeding

The system MUST provide `scripts/bootstrap_db.py` (runnable as `python -m scripts.bootstrap_db`) that creates the schema idempotently and `scripts/seed_colsubsidio.py` (runnable as `python -m scripts.seed_colsubsidio`) that inserts 44 proyectos verbatim and 15 mock afiliados with predictable "demo star" cedulas.

> **Recorded decision (spec/design conflict).** An earlier design revision proposed
> relying solely on the FastAPI lifespan's `Base.metadata.create_all(checkfirst=True)`
> and dropping the bootstrap script. The script is retained because the lifespan path
> swallows `init_db()` failures with a warning (`app/main.py`), so a schema failure
> there yields a process that answers `GET /health` with 200 and no tables. An operator-
> runnable script returns a real exit code, which the ordered-run scenario below asserts.
> The lifespan `create_all` remains as a convenience for local `uvicorn --reload`; it is
> not the contract.

#### Scenario: bootstrap_db is idempotent

- GIVEN an existing populated Postgres `vivi` database
- WHEN `python -m scripts.bootstrap_db` runs once
- THEN all tables (conversations, messages, leads, afiliados_colsubsidio, proyectos_colsubsidio) exist with correct indexes and unique constraints
- WHEN `python -m scripts.bootstrap_db` runs a second time
- THEN no error is raised (idempotent) and `create_all(checkfirst=True)` is observed
- AND the script performs no destructive `DROP` under any environment

#### Scenario: Destructive reset is a separate, explicit command

- GIVEN an operator needs to regenerate the `leads` table after a schema change
- WHEN they run `python -m scripts.reset_db --yes`
- THEN the script drops and recreates the affected tables
- AND neither `bootstrap_db`, `seed_colsubsidio`, nor the FastAPI lifespan MUST ever perform a `DROP`, regardless of `APP_ENV`
- AND a destructive path gated only on `app_env == "development"` MUST NOT be used, because `development` is the shipped default in `.env.example`, in `docker-compose.yml`, and in the `Settings` field default

#### Scenario: seed_colsubsidio inserts 44 proyectos verbatim

- GIVEN an empty `proyectos_colsubsidio` table after `bootstrap_db`
- WHEN `python -m scripts.seed_colsubsidio` runs
- THEN exactly 44 rows are inserted with the exact values from the source spreadsheet (`Preguntas y modelo tabla de datos.xlsx` sheet `Proyectos`, which holds 1 header row plus 44 data rows)
- AND the sparse `ABETO` and `LA ARBOLEDA` rows, the `VIBO ONCE` `B2` row (Tipo=Municipio='VIS'), and the `VERSALLES` `E` row where `area_privada_m2` (60,6) exceeds `area_construida_m2` (56,29) are all present unchanged

#### Scenario: seed_colsubsidio parses the source decimal format

- GIVEN source area cells written with comma decimal separators (`56,29`, `60,6`)
- WHEN the seed inserts them
- THEN they are stored as `Numeric(10,2)` values `56.29` and `60.60`
- AND blank cells (`LOS NOGALES` `valor_vis_smmlv`, `ABETO` `area_privada_m2`, `LA ARBOLEDA` `area_privada_m2`/`cantidad_habitaciones`/`cantidad_banos`) are stored as NULL

#### Scenario: seed_colsubsidio inserts 15 afiliados distributed

- GIVEN an empty `afiliados_colsubsidio` table
- WHEN `python -m scripts.seed_colsubsidio` runs
- THEN exactly 15 rows are inserted with `is_seed=true`
- AND the distribution covers all three `categoria_afiliado` values (A, B, C) and at least one row in each of the six credit bands
- AND at least one row carries `ha_recibido_subsidio=true`, so the absolute-disqualifier path is demonstrable

> The source workbook's `Afiliados Colsubsidio` sheet contains a header row and the
> credit-band legend but **zero data rows**. All 15 afiliados are therefore fabricated
> for the demo; the distribution above is the only constraint on them, and the seed
> script is their sole source of truth.

#### Scenario: Re-running the seed is idempotent

- GIVEN `afiliados_colsubsidio` and `proyectos_colsubsidio` already seeded
- WHEN `python -m scripts.seed_colsubsidio` runs a second time
- THEN the afiliado rows previously inserted with `is_seed=true` are replaced (via `DELETE WHERE is_seed=true` then re-INSERT) — non-seed manual rows survive
- AND proyectos still hold exactly 44 rows, not 88

#### Scenario: Sparse-modelo rows survive the idempotent re-seed

- GIVEN `ABETO` and `LA ARBOLEDA`, whose source `Modelo` cell is blank
- WHEN the seed runs twice using `INSERT … ON CONFLICT (proyecto, modelo) DO NOTHING`
- THEN both rows are present exactly once, because `modelo` is stored as `''` under a `NOT NULL DEFAULT ''` column
- AND a nullable `modelo` MUST NOT be used for this key: PostgreSQL does not treat NULLs as conflicting, so `ON CONFLICT` would skip them and the table would grow to 46 rows on the second run

#### Scenario: bootstrap then seed runs in order

- GIVEN a freshly wiped Postgres `vivi` database
- WHEN an operator runs `python -m scripts.bootstrap_db && python -m scripts.seed_colsubsidio`
- THEN the run completes with exit code 0
- AND `SELECT count(*) FROM proyectos_colsubsidio` returns 44, `SELECT count(*) FROM afiliados_colsubsidio WHERE is_seed=true` returns 15

#### Scenario: Scripts and source data are present in the deployed image

- GIVEN the container image built for the Fly demo
- WHEN an operator opens a shell in it and runs `python -m scripts.seed_colsubsidio`
- THEN the command resolves — `scripts/` and any source data the seed reads are included in the image
- AND a Dockerfile that copies only `pyproject.toml`, `README.md` and `app/` MUST NOT be used

### Requirement: Demo-Star Afiliados

The seed script MUST include 3 hardcoded "demo star" afiliados whose cedulas are predictable per categoria × score band, and the README MUST list those cedulas so a juror can demo with deterministic outcomes.

#### Scenario: Three demo stars documented and present

- GIVEN `python -m scripts.seed_colsubsidio` has run
- WHEN a lookup is performed on each of the 3 demo-star cedulas listed in the README
- THEN each lookup returns a row whose `(categoria_afiliado, credit_band)` matches the README's claim (one A+Excelente, one B+Bueno, one C+Regular)
- AND the same lookup run later in the day returns the same row (deterministic)
