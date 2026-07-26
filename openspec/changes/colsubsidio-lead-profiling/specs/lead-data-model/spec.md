# Delta for lead-data-model

## ADDED Requirements

### Requirement: Lead and Reference Data Entities

The system MUST replace the existing `LeadEntity` with the Colsubsidio lead schema and MUST add `afiliados_colsubsidio` and `proyectos_colsubsidio` tables. All three MUST be created by `Base.metadata.create_all(checkfirst=True)`. The `leads` row MUST be keyed by `conversation_id` (one conversation = one lead).

#### Scenario: Lead table replacement

- GIVEN the app DB is empty
- WHEN the schema is created
- THEN the `leads` table exists with all canonical lead columns (tipo_documento, numero_documento, afiliado_colsubsidio, nombre_apellido, categoria, otra_caja_compensacion, estado_civil, edad, contrato_laboral, rango_salarial, total_ingresos_mensuales, total_ingresos_familiares_mensuales, antiguedad_laboral, tiene_vivienda_propia, ahorros_o_cesantias, condicion_discapacidad_familiar, numero_pac, tiene_creditos_activos, subsidio_vivienda_anterior, cabeza_de_hogar, lugar_eleccion_vivir, municipio_normalizado, tiempo_compra_deseado, descripcion_vivienda_sueno, status, score, score_credito, score_rating, vis_recommended, classification_reasoning)
- AND the old `LeadEntity` is no longer referenced by any code path

#### Scenario: Enumerated columns store canonical slugs

- GIVEN any of the columns `tipo_documento`, `estado_civil`, `contrato_laboral`, `rango_salarial`, `antiguedad_laboral`, `ahorros_o_cesantias`, `tiempo_compra_deseado`
- WHEN a value is persisted
- THEN it is one of the canonical slugs defined by the `Source Domain Normalization` requirement in `lead-scoring`, or NULL
- AND verbatim source labels MUST NOT be persisted in these columns

#### Scenario: Unique afiliado by composite key

- GIVEN the `afiliados_colsubsidio` table with a unique constraint on (tipo_documento, numero_documento)
- WHEN two rows share the same (tipo_documento, numero_documento) pair
- THEN the second insert MUST be rejected by the database
- AND a lookup by (tipo_documento, numero_documento) returns at most one row

#### Scenario: Unique conversation-to-lead mapping

- GIVEN a `leads` table with a UNIQUE constraint on `conversation_id`
- WHEN two leads are persisted with the same `conversation_id`
- THEN the second persistence MUST upsert (update) the existing row, not insert a duplicate
- AND `save_lead` tool calls preserve previously collected fields

#### Scenario: Lead status transitions

- GIVEN a `leads` row with `status='profiling'`
- WHEN any agent operation modifies the row
- THEN `status` MAY only transition to one of `{'ready', 'nurture', 'nurture_social'}`
- AND transitions from a terminal status (`ready`, `nurture`, `nurture_social`) back to `profiling` or to each other MUST NOT occur

#### Scenario: Status transition guard is enforced in the repository

- GIVEN a `leads` row already at a terminal status
- WHEN `LeadRepository.upsert_by_conversation_id` is called with a different `status`
- THEN the repository raises and the write is rejected
- AND the guard lives in `LeadRepository`, so every writer (`save_lead`, `classify_lead`, the `scoring` node) inherits it rather than re-implementing it

#### Scenario: Score rating band labels

- GIVEN a lead row with a value in `score_rating`
- WHEN the value is read
- THEN it MUST be one of the literal labels {`Malo`, `Regular`, `Aceptable`, `Bueno`, `Muy Bueno`, `Excelente`}
- AND it MUST be derived from the lead's **`score_credito`** (range 150-950) per the credit-band mapping (150-499 Malo · 500-649 Regular · 650-699 Aceptable · 700-749 Bueno · 750-799 Muy Bueno · 800-950 Excelente)
- AND it MUST NOT be derived from `score`, which is the 0-100 overall score and shares no interval with the credit bands

#### Scenario: Proyectos table preserves source quirks

- GIVEN `proyectos_colsubsidio` is seeded with the 44 provided rows
- WHEN the table is read
- THEN all 44 rows are present verbatim, including the `VIBO ONCE` row whose `modelo` is `B2` and where both `tipo` and `municipio` equal `'VIS'`, the `VERSALLES` row with `modelo='E'` whose `area_privada_m2` (60,6) exceeds its `area_construida_m2` (56,29), and the two sparse rows `ABETO` and `LA ARBOLEDA`
- AND no row is silently dropped or normalized

#### Scenario: Sparse rows carry empty strings on the natural key, NULL elsewhere

- GIVEN the `ABETO` and `LA ARBOLEDA` source rows, both of which have a blank `Modelo`
- WHEN they are persisted
- THEN `modelo` is stored as the empty string `''` under a `NOT NULL DEFAULT ''` column, so the `(proyecto, modelo)` unique constraint can match them
- AND all other blank source cells (`direccion`, `area_privada_m2`, `cantidad_habitaciones`, `cantidad_banos`, `valor_vis_smmlv`) are stored as NULL
- AND a UNIQUE constraint on a nullable `modelo` MUST NOT be used, because PostgreSQL does not treat NULLs as conflicting and the idempotent re-seed would duplicate both rows

#### Scenario: Source decimal format is parsed, not stored verbatim

- GIVEN a source area value written with a comma decimal separator (e.g. `56,29`)
- WHEN the seed persists it
- THEN it is parsed to a `Numeric(10,2)` value of `56.29`
- AND a blank source cell yields NULL, not `0`

#### Scenario: Municipio normalization for project lookup

- GIVEN the `Lugar de elección para vivir` options offered to the lead (`Bogotá norte`, `Bogotá centro`, `Bogotásur`, `Soacha`, `Chía`, `Tocancipá`, `Girardot`, `Ricaurte`, `Ubaté`)
- AND the `municipio` values present in `proyectos_colsubsidio` (`Bogota`, `Chía`, `Girardot`, `Ricaurte`, `Soacha`, `Tocancipá`, `Ubate`, `VIS`)
- WHEN a lead's `lugar_eleccion_vivir` is persisted
- THEN `municipio_normalizado` is also persisted, mapping `Bogotá norte`/`Bogotá centro`/`Bogotásur` → `Bogota` and `Ubaté` → `Ubate`, with the remaining five options mapping to themselves
- AND project lookups join on `municipio_normalizado`, never on the raw `lugar_eleccion_vivir`
- AND the corrupt source value `municipio='VIS'` (the `VIBO ONCE` `B2` row) is treated as `Bogota` at lookup time while remaining `'VIS'` in the stored row

#### Scenario: Afiliado table exposure

- GIVEN the `afiliados_colsubsidio` table is seeded
- WHEN `lookup_afiliado` queries a known cedula
- THEN the returned record exposes `categoria_afiliado` (A/B/C), a `score_credito` integer, `ha_recibido_subsidio` boolean, `fecha_nacimiento` (for edad derivation), `estado_civil`, `salario_base_cotizacion`, `categoria`, and an `is_seed` boolean
- AND `is_seed=true` rows are reserved for the seed script's idempotent re-seed path

#### Scenario: Caja de compensación is a controlled vocabulary

- GIVEN the source sheet enumerates 30+ named cajas de compensación (Cafam, Compensar, Colsubsidio, Comfacundi, Comfaboy, Comfama, …)
- WHEN `otra_caja_compensacion` is persisted
- THEN the value is one of the enumerated caja names, the literal `ninguna`, or NULL
- AND free text outside that vocabulary MUST NOT be persisted, so the "already affiliated elsewhere" regulatory branch stays analyzable
