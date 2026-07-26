# Delta for lead-scoring

## ADDED Requirements

### Requirement: Deterministic Lead Scoring

The system MUST compute a lead score via a pure-Python scorer `app/services/lead_scorer.py` with signature `score_lead(lead, afiliado) -> (score: int, rating_label: str, classification: str, reasoning: str)`. The scorer MUST be deterministic (same input → same output, no randomness, no time-of-day dependencies) and MUST NOT make LLM or network calls.

#### Scenario: Score range invariant

- GIVEN any combination of lead and afiliado inputs (including NULL/missing fields)
- WHEN `score_lead(lead, afiliado)` runs
- THEN the returned `score` is an integer in the closed interval [0, 100]
- AND `rating_label` is one of {Malo, Regular, Aceptable, Bueno, Muy Bueno, Excelente}

#### Scenario: Bucket credits are capped at the documented maxima

- GIVEN a lead that would exceed every bucket maximum
- WHEN the scorer sums per-bucket contributions
- THEN the Credit_bucket contribution MUST NOT exceed 25, Categoria 15, Ingreso 20, Ahorro 15, Tiempo_compra 10, Estabilidad 15
- AND red-flag adjustments (vivienda_propia+VIS -15, creditos_activos -5, discapacidad/PAC +8) are applied additively to the sum, then clamped to [0, 100]

#### Scenario: Subsidio previo absolute override

- GIVEN a lead whose numeric score would otherwise classify as `ready` (>= 60) but `subsidio_vivienda_anterior=true`
- WHEN `score_lead` runs
- THEN `classification='nurture'` regardless of the numeric score
- AND `reasoning` MUST contain the literal substring "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
- AND the numeric `score` is still computed and returned for analytics

#### Scenario: READY threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and computed score >= 60
- WHEN the scorer runs
- THEN `classification='ready'`

#### Scenario: NURTURE threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and computed score in [30, 59]
- WHEN the scorer runs
- THEN `classification='nurture'`

#### Scenario: NURTURE_SOCIAL threshold

- GIVEN a lead with `subsidio_vivienda_anterior=false` and computed score < 30
- WHEN the scorer runs
- THEN `classification='nurture_social'`

#### Scenario: Red flag — vivienda propia pursuing VIS

- GIVEN a lead with `tiene_vivienda_propia=true` and a purchase intent identified as VIS (per the VIS/NO-VIS type of the recommended project or `lugar_eleccion_vivir` mapping)
- WHEN the scorer runs
- THEN the score subtracts 15 (vivienda_propia+VIS rule)

#### Scenario: Red flag — creditos activos

- GIVEN a lead with `tiene_creditos_activos=true`
- WHEN the scorer runs
- THEN the score subtracts 5

#### Scenario: Red flag — discapacidad/PAC bonus

- GIVEN a lead with `condicion_discapacidad_familiar=true` OR `numero_pac > 0`
- WHEN the scorer runs
- THEN the score adds 8

#### Scenario: No-afiliado credit bureau simulation

- GIVEN a no-afiliado lead (afiliado=null) with `numero_documento='12345678'`
- WHEN the scorer (or its bureau-simulation helper) derives a credit band from the cedula
- THEN the derived band is deterministic: same `numero_documento` always yields the same band
- AND the returned `reasoning` labels the band as "simulated bureau"

#### Scenario: Demo reproducibility — same input, same output

- GIVEN the same `(lead, afiliado)` tuple
- WHEN `score_lead` runs twice in two separate process invocations
- THEN both invocations return the same `(score, rating_label, classification, reasoning)` tuple