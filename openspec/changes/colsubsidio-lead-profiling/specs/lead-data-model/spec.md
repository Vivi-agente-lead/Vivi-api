# Delta for lead-data-model

## ADDED Requirements

### Requirement: Lead and Reference Data Entities

The system MUST replace the existing `LeadEntity` with the Colsubsidio lead schema and MUST add `afiliados_colsubsidio` and `proyectos_colsubsidio` tables. All three MUST be created by `Base.metadata.create_all(checkfirst=True)` during app startup. The `leads` row MUST be keyed by `conversation_id` (one conversation = one lead).

#### Scenario: Lead table replacement

- GIVEN the app DB is empty
- WHEN `init_db()` runs during app startup
- THEN the `leads` table exists with all canonical lead columns (tipo_documento, numero_documento, afiliado_colsubsidio, nombre_apellido, categoria, otra_caja_compensacion, estado_civil, edad, empleado_o_independiente, rango_salarial, total_ingresos_mensuales, total_ingresos_familiares_mensuales, antiguedad_laboral, tiene_vivienda_propia, ahorros_o_cesantias, condicion_discapacidad_familiar, numero_pac, tiene_creditos_activos, subsidio_vivienda_anterior, cabeza_de_hogar, lugar_eleccion_vivir, tiempo_compra_deseado, descripcion_vivienda_sueno, status, score, score_rating, classification_reasoning)
- AND the old `LeadEntity` is no longer referenced by any code path

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

#### Scenario: Score rating band labels

- GIVEN a lead row with a value in `score_rating`
- WHEN the value is read
- THEN it MUST be one of the literal labels {`Malo`, `Regular`, `Aceptable`, `Bueno`, `Muy Bueno`, `Excelente`}
- AND it MUST be derived from the lead's `score` band per the credit-band mapping (150-499 Malo · 500-649 Regular · 650-699 Aceptable · 700-749 Bueno · 750-799 Muy Bueno · 800-950 Excelente).

#### Scenario: Proyectos table preserves source quirks

- GIVEN `proyectos_colsubsidio` is seeded with the 43 provided rows
- WHEN the table is read
- THEN all 43 rows are present verbatim, including the `VIBO ONCE` row where both `tipo` and `municipio` equal `'VIS'`, the row whose `area_privada_m2` exceeds `area_construida_m2`, and the sparse `ABETO` row (with NULLs on sparse columns)
- AND no row is silently dropped or normalized

#### Scenario: Afiliado table exposure

- GIVEN the `afiliados_colsubsidio` table is seeded
- WHEN `lookup_afiliado` queries a known cedula
- THEN the returned record exposes `categoria_afiliado` (A/B/C), a `score_credito` integer, `ha_recibido_subsidio` boolean, `fecha_nacimiento` (for edad derivation), `estado_civil`, `salario_base_cotizacion`, `categoria`, and an `is_seed` boolean
- AND `is_seed=true` rows are reserved for the seed script's idempotent re-seed path