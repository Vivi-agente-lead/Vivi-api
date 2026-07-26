# Delta for seed-and-bootstrap

## ADDED Requirements

### Requirement: Idempotent DB Bootstrap and Colsubsidio Seeding

The system MUST provide `scripts/bootstrap_db.py` (runnable as `python -m scripts.bootstrap_db`) that recreates the schema idempotently and `scripts/seed_colsubsidio.py` (runnable as `python -m scripts.seed_colsubsidio`) that inserts 43 proyectos verbatim and 15 mock afiliados with predictable "demo star" cedulas.

#### Scenario: bootstrap_db is idempotent

- GIVEN an existing populated Postgres `vivi` database
- WHEN `python -m scripts.bootstrap_db` runs once
- THEN all tables (conversations, leads, afiliados_colsubsidio, proyectos_colsubsidio) exist with correct indexes and unique constraints
- WHEN `python -m scripts.bootstrap_db` runs a second time
- THEN no error is raised (idempotent) and `create_all(checkfirst=True)` is observed (no destructive DROP unless the script opts in)

#### Scenario: seed_colsubsidio inserts 43 proyectos verbatim

- GIVEN an empty `proyectos_colsubsidio` table after `bootstrap_db`
- WHEN `python -m scripts.seed_colsubsidio` runs
- THEN exactly 43 rows are inserted with the exact values from the source spreadsheet (`Preguntas y modelo tabla de datos.xlsx` sheet 2)
- AND the sparse `ABETO` row, the `VIBO ONCE` row (Tipo=Municipio='VIS'), and the row where `area_privada_m2 > area_construida_m2` are all present unchanged

#### Scenario: seed_colsubsidio inserts 15 afiliados distributed

- GIVEN an empty `afiliados_colsubsidio` table
- WHEN `python -m scripts.seed_colsubsidio` runs
- THEN exactly 15 rows are inserted with `is_seed=true`
- AND the distribution covers all three `categoria` values (A, B, C) and a sample of credit bands

#### Scenario: Re-running the seed is idempotent

- GIVEN `afiliados_colsubsidio` and `proyectos_colsubsidio` already seeded
- WHEN `python -m scripts.seed_colsubsidio` runs a second time
- THEN the afiliado rows previously inserted with `is_seed=true` are replaced (via `DELETE WHERE is_seed=true` then re-INSERT) — non-seed manual rows survive
- AND proyectos use an ON CONFLICT-by-composite-key or DELETE-then-INSERT strategy so the table still holds exactly 43 rows, not 86

#### Scenario: bootstrap then seed runs in order

- GIVEN a freshly wiped Postgres `vivi` database
- WHEN an operator runs `python -m scripts.bootstrap_db && python -m scripts.seed_colsubsidio`
- THEN the run completes with exit code 0
- AND `SELECT count(*) FROM proyectos_colsubsidio` returns 43, `SELECT count(*) FROM afiliados_colsubsidio WHERE is_seed=true` returns 15

### Requirement: Demo-Star Afiliados

The seed script MUST include 3 hardcoded "demo star" afiliados whose cedulas are predictable per categoria × score band, and the README MUST list those cedulas so a juror can demo with deterministic outcomes.

#### Scenario: Three demo stars documented and present

- GIVEN `python -m scripts.seed_colsubsidio` has run
- WHEN a lookup is performed on each of the 3 demo-star cedulas listed in the README
- THEN each lookup returns a row whose `(categoria, credit_band)` matches the README's claim (one A+Excelente, one B+Bueno, one C+Regular)
- AND the same lookup run later in the day returns the same row (deterministic)