# Delta for lead-scoring

## ADDED Requirements

### Requirement: Source Domain Normalization

Every enumerated lead field MUST be normalized from its verbatim source label
(`docs/Preguntas y modelo tabla de datos.xlsx`, `Leads` sheet) to a canonical slug
before it reaches the scorer. The scorer MUST key exclusively off canonical slugs and
MUST NOT perform substring matching on user- or LLM-supplied text.

Normalization lives in a pure module (`app/services/domain_normalizer.py`); the
verbatim labels remain the vocabulary shown to the user and to the LLM.

> **v2 migration** (`docs/v2-impact-analysis.md`): `tipo_documento` gains a
> sixth option (`Carné Diplomático`); `contrato_laboral` gains a fourth
> (`Independiente`, now distinct from `Prestacion de servicios` — the v2
> sheet's column O and column P disagree on this, and column O, the four-value
> list, is followed; see the apply report); `antiguedad_laboral` is removed
> (the field it backed no longer exists); `interes_afiliacion` and
> `preferencia_vis` are added.

| Field | Verbatim source labels | Canonical slugs |
|---|---|---|
| `tipo_documento` | Cédula de ciudadanía · Cédula de extranjería · Pasaporte · Permiso Especial de Permanencia · Permiso por Protección Temporal · Carné Diplomático | `CC` · `CE` · `PA` · `PEP` · `PPT` · `CD` |
| `estado_civil` | Soltero · Casado · Divorciado · Union libre · Separado · Viudo | `soltero` · `casado` · `divorciado` · `union_libre` · `separado` · `viudo` |
| `contrato_laboral` | Termino fijo · Termino indefinido · Prestacion de servicios · Independiente | `termino_fijo` · `termino_indefinido` · `prestacion_servicios` · `independiente` |
| `rango_salarial` | 2 millones o menos · 2 a 4 millones · 4 a 8 millones · 8 a 10 millones · mas de 10 millones | `hasta_2m` · `2_4m` · `4_8m` · `8_10m` · `mas_10m` |
| `ahorros_o_cesantias` | No tengo ahorros. · Menos de $3 millones · Entre $3 y $10 millones · Entre $10 y $20 millones · Entre $20 y $40 millones · Más de $40 millones | `ninguno` · `menos_3m` · `3_10m` · `10_20m` · `20_40m` · `mas_40m` |
| `tiempo_compra_deseado` | 3 meses · 6 meses · 1 año · 2 años · No sé | `3_meses` · `6_meses` · `1_ano` · `2_anos` · `no_se` |
| `interes_afiliacion` (v2, no-afiliado path only) | No, estoy afiliado a otra caja de compensación · Si estoy interesado en afiliarme · No, prefiero en otro momento. | `afiliado_otra_caja` · `interesado_afiliarse` · `prefiere_otro_momento` |
| `preferencia_vis` (v2) | VIS · NO VIS · Ambas | `vis` · `no_vis` · `ambas` |

Two predicates are derived, never collected:

- `tiene_pareja` := `estado_civil in {casado, union_libre}`
- `es_empleado` := `contrato_laboral in {termino_fijo, termino_indefinido}`

A third value is derived, never collected, and gated to the no-afiliado path
(`docs/v2-impact-analysis.md` §5):

- `otra_caja_compensacion` := `interes_afiliacion == "afiliado_otra_caja"` (for
  an afiliado, both `interes_afiliacion` and `otra_caja_compensacion` stay
  `NULL` — the question is never asked)

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

> **v2 migration**: this scenario no longer asserts `cabeza_de_hogar` — the
> field is removed (absent from the v2 sheet).

### Requirement: Deterministic Lead Scoring

The system MUST compute a lead score via a pure-Python scorer `app/services/lead_scorer.py` with signature `score_lead(lead, afiliado) -> (score: int, rating_label: str, classification: str, reasoning: str)`. The scorer MUST be deterministic (same input → same output, no randomness, no time-of-day dependencies) and MUST NOT make LLM or network calls.

`classification` and the persisted `lead.status` MUST carry the same value from the
single domain {`calificado`, `nutrible`, `no_calificado`} (v2 rename of
{`ready`, `nurture`, `nurture_social`} — see `lead-data-model`'s "Lead status
transitions" scenario).

#### Scenario: Score range invariant

- GIVEN any combination of lead and afiliado inputs (including NULL/missing fields)
- WHEN `score_lead(lead, afiliado)` runs
- THEN the returned `score` is an integer in the closed interval [0, 100]
- AND `rating_label` is one of {Malo, Regular, Aceptable, Bueno, Muy Bueno, Excelente}
- AND `rating_label` is the credit band of `score_credito` (150-950), NOT a function of `score`

#### Scenario: Bucket credits are capped at the documented maxima

> **v2 re-budget** (`docs/v2-impact-analysis.md` §10, §12): `antiguedad_
> laboral` is removed, so Bucket 6 ("Estabilidad", contract type × tenure) has
> no input left. It is replaced by "Capacidad" (disposable-income ratio,
> `total_ingresos_mensuales` vs `gastos_mensuales`), keeping the same 15-point
> ceiling so the six maxima still sum to 100. The `discapacidad/PAC` red flag
> loses its `condicion_discapacidad_familiar` trigger (field removed); only
> `numero_pac > 0` remains, unchanged at `+8`.

- GIVEN a lead that would exceed every bucket maximum
- WHEN the scorer sums per-bucket contributions
- THEN the Credito bucket contribution MUST NOT exceed 25, Afiliacion 15, Ingreso 20, Ahorro 15, Tiempo_compra 10, Capacidad 15
- AND the six maxima sum to exactly 100
- AND red-flag adjustments (vivienda_propia+VIS -15, creditos_activos -5, PAC +8) are applied additively to the sum, then clamped to [0, 100]

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

#### Scenario: Bucket 6 — Capacidad (max 15) [MODIFIED — v2, replaces Estabilidad]

> Supersedes the v1 "Bucket 6 — Estabilidad" scenario. `antiguedad_laboral` no
> longer exists (`docs/v2-impact-analysis.md` §3); the replacement bucket is
> this change's own design decision (not stated verbatim in either v2 source
> document), documented in full in `app/services/lead_scorer.py`'s
> `CAPACIDAD_BANDS` docstring.

- GIVEN a lead with both `total_ingresos_mensuales` and `gastos_mensuales` set, `ingreso > 0`
- WHEN the Capacidad bucket is evaluated
- THEN `ratio := (ingreso - gastos) / ingreso` is computed
- AND points are awarded `ratio >= 0.50` → 15, `0.35 <= ratio < 0.50` → 11, `0.20 <= ratio < 0.35` → 7, `0.05 <= ratio < 0.20` → 3, `ratio < 0.05` → 0
- GIVEN `total_ingresos_mensuales` or `gastos_mensuales` is NULL, unrecognized, or `total_ingresos_mensuales <= 0`
- WHEN the bucket is evaluated
- THEN the contribution is `0`

#### Scenario: `pos_subsidio` rule [ADDED — v2]

> The v2 flow diagram branches from the (no-afiliado-only) `interes_
> afiliacion` question to `Setear variable pos_subsidio = 0` when the lead is
> affiliated to another caja de compensación (`docs/v2-impact-analysis.md`
> §5). This is a named rule, not a scored bucket: it does not change the
> numeric `score` (neither v2 source document states a point penalty), and it
> is never folded into an existing bucket — it surfaces its own line in
> `classification_reasoning`.

- GIVEN a no-afiliado lead with `otra_caja_compensacion=true` (derived from `interes_afiliacion == "afiliado_otra_caja"`)
- WHEN the scorer runs
- THEN `pos_subsidio` is set to `0`, and `reasoning` contains a line naming it
- AND the numeric `score` is unaffected
- AND the lead is NOT disqualified — `pos_subsidio=0` reduces purchasing capacity, it does not gate `calificado`
- GIVEN an afiliado lead (the affiliation question is gated to non-affiliates, so `otra_caja_compensacion` is always NULL for them)
- WHEN the scorer runs
- THEN `pos_subsidio` is `1` — a NULL `otra_caja_compensacion` MUST NOT be treated as "affiliated elsewhere" by truthiness
- GIVEN a no-afiliado lead with `otra_caja_compensacion` NULL or `false`
- WHEN the scorer runs
- THEN `pos_subsidio` is `1`

#### Scenario: Subsidio previo absolute override

- GIVEN a lead whose numeric score would otherwise classify as `calificado` but `subsidio_vivienda_anterior=true`
- WHEN `score_lead` runs
- THEN `classification='nutrible'` regardless of the numeric score
- AND `reasoning` MUST contain the literal substring "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
- AND the numeric `score` is still computed and returned for analytics
- AND the override applies identically to afiliado and no-afiliado leads, and to every `estado_civil`

#### Scenario: READY threshold is affiliation-dependent

- GIVEN an afiliado lead with `subsidio_vivienda_anterior=false` and computed score >= 60
- WHEN the scorer runs
- THEN `classification='calificado'`
- GIVEN a no-afiliado lead with `subsidio_vivienda_anterior=false` and computed score >= 75
- WHEN the scorer runs
- THEN `classification='calificado'`
- GIVEN a no-afiliado lead with computed score in [60, 74]
- WHEN the scorer runs
- THEN `classification='nutrible'` (the affiliate threshold does not apply)

#### Scenario: NUTRIBLE threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and a computed score at or above 30 but below its applicable READY threshold
- WHEN the scorer runs
- THEN `classification='nutrible'`

#### Scenario: NO_CALIFICADO threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and computed score < 30
- WHEN the scorer runs
- THEN `classification='no_calificado'`

#### Scenario: Red flag — vivienda propia pursuing VIS [MODIFIED — graph-topology migration]

> Amends the v1 "vivienda propia pursuing VIS" scenario: `preferencia_vis`, a
> field v2 collects directly, now takes priority over the derived
> `vis_recommended` when present (decided, `docs/v2-impact-analysis.md` §4,
> §12 "The VIS red flag").

- GIVEN a lead with `tiene_vivienda_propia=true` and `preferencia_vis` in {`vis`, `ambas`}
- WHEN the scorer runs
- THEN the score subtracts 15, regardless of the derived `vis_recommended` value
- GIVEN a lead with `tiene_vivienda_propia=true` and `preferencia_vis='no_vis'`
- WHEN the scorer runs
- THEN no deduction is applied, even if `vis_recommended=true` — the stated preference suppresses the derived one
- GIVEN a lead with `tiene_vivienda_propia=true`, `preferencia_vis` NULL (not collected — the graph-topology migration's linear qualification flow does not yet ask it; see `leads-conversational-flow`), and `vis_recommended=true`
- WHEN the scorer runs
- THEN the score subtracts 15 — the fallback to the derived value applies only when `preferencia_vis` was never collected
- GIVEN `preferencia_vis` NULL and `vis_recommended=false` or NULL
- WHEN the scorer runs
- THEN no deduction is applied

#### Scenario: Red flag — creditos activos

- GIVEN a lead with `tiene_creditos_activos=true`
- WHEN the scorer runs
- THEN the score subtracts 5

#### Scenario: Red flag — PAC bonus [MODIFIED — v2]

> Supersedes the v1 "discapacidad/PAC bonus" scenario: `condicion_
> discapacidad_familiar` is removed (`docs/v2-impact-analysis.md` §3); only
> the `numero_pac` trigger remains. The `+8` value is unchanged.

- GIVEN a lead with `numero_pac > 0`
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
> individual lead. A hard gate (`afiliado_colsubsidio=false` ⇒ never `calificado`) would
> contradict the required scenario "Happy path no-afiliado reaches READY" in
> `leads-conversational-flow`, and the brief itself frames the no-afiliado regulatory
> bottleneck as worth handling rather than excluding. The target is therefore driven by
> two structural levers — Bucket 2 (no-afiliado scores `0`) and the affiliation-
> dependent READY threshold (60 vs 75) — and monitored.
>
> **Alternative, if the team prefers a hard gate**: replace this requirement with
> "`classification='calificado'` REQUIRES `afiliado_colsubsidio=true`", drop the 75
> threshold, and amend the no-afiliado READY scenario in `leads-conversational-flow`.
>
> **v2 rename** (`docs/v2-impact-analysis.md` §7): `ready` → `calificado`
> throughout this requirement; the decision and the two structural levers are
> unchanged.

#### Scenario: Affiliation is a strictly positive signal at equal credit standing

- GIVEN two leads identical in every field, and whose credit standing lands in the same band — one afiliado with that `score_credito`, one no-afiliado whose `numero_documento` simulates to the same band
- WHEN both are scored
- THEN the afiliado's score exceeds the no-afiliado's by exactly `CATEGORIA_PTS[categoria_afiliado]` (15 for A, 11 for B, 7 for C)
- AND the no-afiliado lead requires a higher score to reach `calificado` (75 versus 60)

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
- WHEN the affiliate share of qualified leads is queried as `count(status='calificado' AND afiliado_colsubsidio=true) / count(status='calificado')`
- THEN the query runs against persisted columns with no recomputation
- AND the value is reported in the juror walkthrough
