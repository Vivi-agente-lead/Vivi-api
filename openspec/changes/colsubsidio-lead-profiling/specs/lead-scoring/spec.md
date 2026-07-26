# Delta for lead-scoring

## ADDED Requirements

### Requirement: Source Domain Normalization

Every enumerated lead field MUST be normalized from its verbatim source label
(`docs/Preguntas y modelo tabla de datos.xlsx`, `Leads` sheet) to a canonical slug
before it reaches the scorer. The scorer MUST key exclusively off canonical slugs and
MUST NOT perform substring matching on user- or LLM-supplied text.

Normalization lives in a pure module (`app/services/domain_normalizer.py`); the
verbatim labels remain the vocabulary shown to the user and to the LLM.

| Field | Verbatim source labels | Canonical slugs |
|---|---|---|
| `tipo_documento` | Cédula de ciudadanía · Cédula de extranjería · Pasaporte · Permiso Especial de Permanencia · Permiso por Protección Temporal | `CC` · `CE` · `PA` · `PEP` · `PPT` |
| `estado_civil` | Soltero · Casado · Divorciado · Union libre · Separado · Viudo | `soltero` · `casado` · `divorciado` · `union_libre` · `separado` · `viudo` |
| `contrato_laboral` | Termino fijo · Termino indefinido · Prestacion de servicios | `termino_fijo` · `termino_indefinido` · `prestacion_servicios` |
| `rango_salarial` | 2 millones o menos · 2 a 4 millones · 4 a 8 millones · 8 a 10 millones · mas de 10 millones | `hasta_2m` · `2_4m` · `4_8m` · `8_10m` · `mas_10m` |
| `antiguedad_laboral` | Menos de 1 año · 1 a 2 años · Mas de dos años | `menos_1a` · `1_2a` · `mas_2a` |
| `ahorros_o_cesantias` | No tengo ahorros. · Menos de $3 millones · Entre $3 y $10 millones · Entre $10 y $20 millones · Entre $20 y $40 millones · Más de $40 millones | `ninguno` · `menos_3m` · `3_10m` · `10_20m` · `20_40m` · `mas_40m` |
| `tiempo_compra_deseado` | 3 meses · 6 meses · 1 año · 2 años · No sé | `3_meses` · `6_meses` · `1_ano` · `2_anos` · `no_se` |

Two predicates are derived, never collected:

- `tiene_pareja` := `estado_civil in {casado, union_libre}`
- `es_empleado` := `contrato_laboral in {termino_fijo, termino_indefinido}`

#### Scenario: Verbatim labels normalize to canonical slugs

- GIVEN a lead field carrying a verbatim source label from the table above
- WHEN the normalizer runs
- THEN the field is stored on the `leads` row as the corresponding canonical slug
- AND the scorer receives only canonical slugs

#### Scenario: Unrecognized value fails closed

- GIVEN a value that matches no verbatim label and no canonical slug for its field
- WHEN the normalizer runs
- THEN the field is set to `NULL` and the bucket that consumes it contributes `0`
- AND the unrecognized raw value is recorded in `classification_reasoning`
- AND the scorer MUST NOT substitute a mid-range default for an unrecognized value

#### Scenario: Estado civil beyond the three-value assumption

- GIVEN a lead with `estado_civil` in {`divorciado`, `separado`, `viudo`}
- WHEN `tiene_pareja` is derived
- THEN `tiene_pareja` is `false`
- AND the lead follows the same collection path as `soltero`
- AND `cabeza_de_hogar` is `true`

### Requirement: Deterministic Lead Scoring

The system MUST compute a lead score via a pure-Python scorer `app/services/lead_scorer.py` with signature `score_lead(lead, afiliado) -> (score: int, rating_label: str, classification: str, reasoning: str)`. The scorer MUST be deterministic (same input → same output, no randomness, no time-of-day dependencies) and MUST NOT make LLM or network calls.

`classification` and the persisted `lead.status` MUST carry the same value from the
single domain {`ready`, `nurture`, `nurture_social`}.

#### Scenario: Score range invariant

- GIVEN any combination of lead and afiliado inputs (including NULL/missing fields)
- WHEN `score_lead(lead, afiliado)` runs
- THEN the returned `score` is an integer in the closed interval [0, 100]
- AND `rating_label` is one of {Malo, Regular, Aceptable, Bueno, Muy Bueno, Excelente}
- AND `rating_label` is the credit band of `score_credito` (150-950), NOT a function of `score`

#### Scenario: Bucket credits are capped at the documented maxima

- GIVEN a lead that would exceed every bucket maximum
- WHEN the scorer sums per-bucket contributions
- THEN the Credito bucket contribution MUST NOT exceed 25, Afiliacion 15, Ingreso 20, Ahorro 15, Tiempo_compra 10, Estabilidad 15
- AND the six maxima sum to exactly 100
- AND red-flag adjustments (vivienda_propia+VIS -15, creditos_activos -5, discapacidad/PAC +8) are applied additively to the sum, then clamped to [0, 100]

#### Scenario: Bucket 1 — Credito (max 25)

- GIVEN a `score_credito` in the closed interval [150, 950]
- WHEN the Credito bucket is evaluated
- THEN points are awarded per the source credit bands: 800-950 → 25, 750-799 → 22, 700-749 → 18, 650-699 → 12, 500-649 → 6, 150-499 → 0
- GIVEN `score_credito` is NULL
- WHEN the bucket is evaluated
- THEN the contribution is `0` and `rating_label` is `Malo`

#### Scenario: Bucket 2 — Afiliacion (max 15)

- GIVEN an afiliado lead with `categoria_afiliado` in {A, B, C}
- WHEN the Afiliacion bucket is evaluated
- THEN points are A → 15, B → 11, C → 7
- GIVEN a no-afiliado lead
- WHEN the bucket is evaluated
- THEN the contribution is `0`
- AND every afiliado categoria therefore scores strictly above every no-afiliado on this bucket

#### Scenario: Bucket 3 — Ingreso (max 20)

- GIVEN a lead with a canonical `rango_salarial`
- WHEN the Ingreso bucket is evaluated
- THEN points are `mas_10m` → 20, `8_10m` → 17, `4_8m` → 14, `2_4m` → 10, `hasta_2m` → 5
- GIVEN `rango_salarial` is NULL or unrecognized
- WHEN the bucket is evaluated
- THEN the contribution is `0`

#### Scenario: Bucket 4 — Ahorro (max 15)

- GIVEN a lead with a canonical `ahorros_o_cesantias`
- WHEN the Ahorro bucket is evaluated
- THEN points are `mas_40m` → 15, `20_40m` → 14, `10_20m` → 12, `3_10m` → 9, `menos_3m` → 5, `ninguno` → 0
- AND the bucket MUST be evaluated by exact slug lookup, never by substring match
- AND `menos_3m` MUST score 5, not 0

#### Scenario: Bucket 5 — Tiempo de compra (max 10)

- GIVEN a lead with a canonical `tiempo_compra_deseado`
- WHEN the Tiempo bucket is evaluated
- THEN points are `3_meses` → 10, `6_meses` → 8, `1_ano` → 5, `2_anos` → 2, `no_se` → 0

#### Scenario: Bucket 6 — Estabilidad (max 15)

- GIVEN an empleado lead (`es_empleado` is true) with a canonical `antiguedad_laboral`
- WHEN the Estabilidad bucket is evaluated
- THEN `termino_indefinido` scores `mas_2a` → 15, `1_2a` → 11, `menos_1a` → 7
- AND `termino_fijo` scores `mas_2a` → 12, `1_2a` → 9, `menos_1a` → 5
- GIVEN an independiente lead (`contrato_laboral='prestacion_servicios'`)
- WHEN the bucket is evaluated
- THEN the contribution is `6` and `antiguedad_laboral` is not consulted
- AND no additive bonus is applied on top of these values (the contract type IS the differentiator)

#### Scenario: Subsidio previo absolute override

- GIVEN a lead whose numeric score would otherwise classify as `ready` but `subsidio_vivienda_anterior=true`
- WHEN `score_lead` runs
- THEN `classification='nurture'` regardless of the numeric score
- AND `reasoning` MUST contain the literal substring "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
- AND the numeric `score` is still computed and returned for analytics
- AND the override applies identically to afiliado and no-afiliado leads, and to every `estado_civil`

#### Scenario: READY threshold is affiliation-dependent

- GIVEN an afiliado lead with `subsidio_vivienda_anterior=false` and computed score >= 60
- WHEN the scorer runs
- THEN `classification='ready'`
- GIVEN a no-afiliado lead with `subsidio_vivienda_anterior=false` and computed score >= 75
- WHEN the scorer runs
- THEN `classification='ready'`
- GIVEN a no-afiliado lead with computed score in [60, 74]
- WHEN the scorer runs
- THEN `classification='nurture'` (the affiliate threshold does not apply)

#### Scenario: NURTURE threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and a computed score at or above 30 but below its applicable READY threshold
- WHEN the scorer runs
- THEN `classification='nurture'`

#### Scenario: NURTURE_SOCIAL threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and computed score < 30
- WHEN the scorer runs
- THEN `classification='nurture_social'`

#### Scenario: Red flag — vivienda propia pursuing VIS

- GIVEN a lead with `tiene_vivienda_propia=true` and `vis_recommended=true`
- WHEN the scorer runs
- THEN the score subtracts 15
- GIVEN `vis_recommended=false` or NULL
- WHEN the scorer runs
- THEN no deduction is applied

#### Scenario: Red flag — creditos activos

- GIVEN a lead with `tiene_creditos_activos=true`
- WHEN the scorer runs
- THEN the score subtracts 5

#### Scenario: Red flag — discapacidad/PAC bonus

- GIVEN a lead with `condicion_discapacidad_familiar=true` OR `numero_pac > 0`
- WHEN the scorer runs
- THEN the score adds 8
- AND the bonus is reachable from every collection path, including `soltero` + afiliado

#### Scenario: No-afiliado credit bureau simulation

- GIVEN a no-afiliado lead (afiliado=null) with `numero_documento='12345678'`
- WHEN the scorer (or its bureau-simulation helper) derives a credit band from the cedula
- THEN the derived band is deterministic: same `numero_documento` always yields the same band
- AND the returned `reasoning` labels the band as "simulado bureau"

#### Scenario: Demo reproducibility — same input, same output

- GIVEN the same `(lead, afiliado)` tuple
- WHEN `score_lead` runs twice in two separate process invocations
- THEN both invocations return the same `(score, rating_label, classification, reasoning)` tuple

### Requirement: Affiliate Share of Qualified Leads (90/10)

`docs/Reto_de_vivienda_Descripcion.md` states a non-negotiable target: **90% of
qualified leads must be Colsubsidio affiliates**. The system MUST encode this as a
measurable distribution target, not as a per-lead hard gate.

> **Recorded decision.** The rule is a property of the READY *set*, not of an
> individual lead. A hard gate (`afiliado_colsubsidio=false` ⇒ never `ready`) would
> contradict the required scenario "Happy path no-afiliado reaches READY" in
> `leads-conversational-flow`, and the brief itself frames the no-afiliado regulatory
> bottleneck as worth handling rather than excluding. The target is therefore driven by
> two structural levers — Bucket 2 (no-afiliado scores `0`) and the affiliation-
> dependent READY threshold (60 vs 75) — and monitored.
>
> **Alternative, if the team prefers a hard gate**: replace this requirement with
> "`classification='ready'` REQUIRES `afiliado_colsubsidio=true`", drop the 75
> threshold, and amend the no-afiliado READY scenario in `leads-conversational-flow`.

#### Scenario: Affiliation is a strictly positive signal at equal credit standing

- GIVEN two leads identical in every field, and whose credit standing lands in the same band — one afiliado with that `score_credito`, one no-afiliado whose `numero_documento` simulates to the same band
- WHEN both are scored
- THEN the afiliado's score exceeds the no-afiliado's by exactly `CATEGORIA_PTS[categoria_afiliado]` (15 for A, 11 for B, 7 for C)
- AND the no-afiliado lead requires a higher score to reach `ready` (75 versus 60)

> **Why the qualifier.** An earlier revision of this scenario read "identical in every
> field except affiliation", which is not satisfiable: credit standing is an *input*
> that differs by construction between the two leads — an afiliado's comes from the
> afiliado record, a no-afiliado's from the cedula simulation. Since the simulation
> draws from the full band table, a no-afiliado can legitimately outrank an afiliado
> whose real `score_credito` is poor. Verified: 30 of 60 sampled documents beat an
> afiliado at `(C, 500)`. Capping the simulation to force the literal property was
> tried and rejected — it made a no-afiliado structurally unable to band `Malo` while
> an afiliado could, which is a worse distortion than the one it fixed.
>
> Affiliation is therefore a positive signal **at equal credit standing**, plus the
> threshold gap. The threshold is the stronger of the two 90/10 levers; the bucket
> alone does not dominate a credit-band difference, and is not intended to.

#### Scenario: The bureau simulation spans the full band table

- GIVEN the deterministic cedula simulation used for no-afiliado leads
- WHEN it is evaluated across a range of `numero_documento` values
- THEN every credit band is reachable, including `Malo`
- AND the simulation MUST NOT be floored or capped to a sub-range, which would make a simulated lead structurally safer than a real afiliado

#### Scenario: Affiliate share is measurable

- GIVEN a populated `leads` table
- WHEN the affiliate share of qualified leads is queried as `count(status='ready' AND afiliado_colsubsidio=true) / count(status='ready')`
- THEN the query runs against persisted columns with no recomputation
- AND the value is reported in the juror walkthrough
