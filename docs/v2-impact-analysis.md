# v2 source documents — flow analysis and impact

Compares `Flujo asesor de venta de vivienda Colsubsidio-v2.json` and
`Preguntas y modelo tabla de datos-v2.xlsx` against the v1 documents the current
implementation was built from.

**Verdict: this is a redesign, not an adjustment.** The flow inverts its entry
point, the branching that shapes the graph disappears, three scored fields are
removed, three new ones appear, and the classification vocabulary changes. The
normalizer, tools, scorer shape and channel adapter survive; the graph topology
largely does not.

Nodes: v1 33 → v2 43. Leads sheet: 47 rows → 17.

---

## 1. The entry point inverts — catalogue first, qualification second

v1 opened cold and recommended projects only at the end, to READY leads.

v2 opens with a project **already in hand**:

> Bienvenido(a), soy Vivi 🏠 y seré tu guía para encontrar tu hogar ideal. El
> proyecto en el cual estás interesado(a) es: Bosque de Turpial. VIS. Su ubicación
> es: {Municipio, ubicación}. Área desde: {área_construida} Habitaciones desde: 1

then `Para continuar elige una opcion:` with three branches:

| Option | Leads to |
|---|---|
| `Quiero saber más de este proyecto` | the qualification flow (consent → documento → …) |
| `Quiero ver otro proyecto.` | `¿Te interesan vivienda VIS, NO VIS o ambas?` → municipio → project menu → back to either the menu or the qualification flow |
| `Salir` | farewell |

This is the largest structural change. In the current implementation `get_projects`
is a terminal action reachable **only** when `status == 'ready'`, and the
`agent-tools` spec states that as a MUST. In v2 browsing the catalogue is the
entry, happens before any qualification, and loops.

**Implication**: the lead arrives with a project and a municipio already chosen,
so `lugar_eleccion_vivir` moves from the end of the flow to the beginning — which
is where the v1 diagram had it and where the current design deliberately moved it
away from. `vis_recommended` also stops being derived at scoring time.

## 2. The four capacity bundles collapse into one

Removed from the diagram:

- `Es empleado y casado o en union libre`
- `Es empleado y soltero`
- `Es independiente y casado o UL`
- `Es independiente y soltero`
- `Está casado o está en union libre`

They existed because v1 asked `total_ingresos_mensuales` for a lead without a
partner and `total_ingresos_familiares_mensuales` for one with a partner, and
asked `antiguedad_laboral` only of employees.

v2 asks one household question of everyone:

> ¿Cuanto suman los ingresos de tu hogar? ¿En promedio cuanto suman los gastos
> mensuales de tu hogar? ¿Tu o tu pareja cuenta con vivienda propia? ¿Cuantas
> personas tiene a cargo? ¿Usted o su pareja han recibido anteriormente un
> subsidio de vivienda? ¿Cuentan con ahorros o cesantias para iniciar?

**`tiene_pareja` and `es_empleado` stop being routing predicates.** Four nodes and
`_route_capacity` collapse to one node. This is the single biggest simplification
available, and it removes the branch the review found most defective.

## 3. Fields removed

| Field | Evidence | Consequence |
|---|---|---|
| `antiguedad_laboral` | absent from the v2 capacity question; column S keeps its option list but has no question | **Bucket 6 (Estabilidad, 15 pts) loses its only input.** 15% of the score has nothing feeding it |
| `condicion_discapacidad_familiar` | no column, absent from the capacity question | the `+8` bonus keeps only its `numero_pac > 0` trigger |
| `cabeza_de_hogar` | no column | derivation and its spec scenario become dead |
| `otra_caja_compensacion` as a caja **name** | column J is now a SI/NO boolean | see §5 |
| `fecha_nacimiento` (no-afiliado path) | replaced by `¿Que edad tienes?` | see §6 |

## 4. Fields added

| Field | Source | Notes |
|---|---|---|
| `gastos_mensuales` | `¿En promedio cuanto suman los gastos mensuales de tu hogar?` | new. Income **minus** expenses is real purchasing capacity; today nothing models a ratio |
| `preferencia_vis` | `¿Te interesan vivienda VIS, NO VIS o ambas?` | stated by the lead instead of derived from the project lookup — changes the input to the −15 red flag |
| `interes_afiliacion` | `¿Te gustaría iniciar tu proceso de afiliación a Colsubsidio?` | see §5 |

Domain widenings:

- `tipo_documento` gains a sixth option, **`Carné Diplomático`** (v1 had five).
- `contrato_laboral` column O offers **four**: `Contrato a termino fijo`,
  `Contrato a termino indefinido`, `Contrato de prestación de servicios`,
  `Independiente`. Today `prestacion_servicios` *is* the independiente bucket;
  v2 separates them. Column P still lists the old three — the two columns
  disagree and need a decision.

## 5. The caja de compensación question is replaced — and the list is deleted

v1 asked whether the lead belonged to any caja, then offered 30+ names, and stored
the name.

v2 asks a different question entirely, with three options (column I):

> **¿Te gustaría iniciar tu proceso de afiliación a Colsubsidio?**
> - No, estoy afiliado a otra caja de compensación
> - Si estoy interesado en afiliarme
> - No, prefiero en otro momento.

Column J carries the derivation verbatim from the sheet:

> La respuesta es "No, estoy afiliado a otra caja de compensación" setear en SI de
> lo contrario NO

So `otra_caja_compensacion` becomes a **derived boolean**, never asked directly,
and the 43-name vocabulary is deleted.

The diagram adds a consequence the sheet does not: the branch out of this question
labelled `SI` leads to **`Setear variable pos_subsidio = 0`**. Being affiliated
elsewhere zeroes the subsidy possibility — the regulatory bottleneck the brief
describes, expressed for the first time as a rule rather than as a field.

**Decided (product owner, 2026-07-26)**: the question is **gated to
non-affiliates**. A confirmed Colsubsidio affiliate already exists in Colsubsidio,
so asking them to begin affiliating is incoherent. The v2 diagram converges both
branches on this node; that is a gap in the drawing, not the intent.

Consequences:

- For an affiliate, `interes_afiliacion` and `otra_caja_compensacion` are never
  collected and stay NULL — mirroring the affiliate-branch behaviour the current
  spec already states ("`lead.otra_caja_compensacion` stays NULL").
- `otra_caja_compensacion` is a **nullable** boolean. NULL means "not applicable,
  never asked"; `false` means "asked, and not affiliated elsewhere". Collapsing
  the two would make an affiliate indistinguishable from a non-affiliate who
  answered no.
- The `pos_subsidio = 0` rule is reachable only on the no-afiliado path, and must
  be guarded on `is True` rather than on a falsy check so a NULL cannot trip it.

## 6. Age is asked, no longer derived

v1 asked `fecha_nacimiento` and computed `edad` server-side, deliberately, so the
model could never supply it. v2 asks `¿Que edad tienes?` directly on the
no-afiliado path; the afiliado path still reads it from the DB
(`Consultar edad en BD`).

This is a **regression in trustworthiness** on a field that gates the whole
conversation (`edad < 18` terminates). Recommend keeping the server-side
derivation and treating the stated age as a cross-check, or accepting the change
knowingly.

## 7. Classification vocabulary changes

`Calificar lead` now fans out to three explicit terminal nodes:

| v2 | current implementation |
|---|---|
| `Calificado` | `ready` |
| `Nutrible` | `nurture` |
| `No calificado` | — **new**; `nurture_social` has no counterpart |

`nurture_social` (the asistente-social path, score < 30) disappears and an explicit
rejection bucket takes its place. Only `Calificado` continues:

`Calificado` → *"Me ha encantado tu entusiasmo…"* → `¿Te conecto con un asesor de
crédito?` → `Enviar notificación por correo`

`No calificado` and `Nutrible` are terminal with no follow-up drawn.

## 8. New capabilities with no code behind them

- **`¿Te conecto con un asesor de crédito?`** — a second hand-off, distinct from
  the asesor comercial one.
- **`Enviar notificación por correo`** — outbound email. No mail transport exists
  in the project.
- **Project browsing loop** — `Mostrar menu de proyectos disponibles en la zona
  seleccionada y segun tipo de vivienda seleccionado`, `Quiero saber más de este
  proyecto`, `Quiero ver otro proyecto.`, `El usuario selecciona volver al menu
  anterior`, `Salir`. A stateful menu with back-navigation, which the current
  linear graph has no concept of.
- **`Leads referidos`** — a new, empty sheet. A referral concept with no
  definition yet; ignore until specified.

## 9. What survives

Worth stating, because most of the engineering does carry over:

- The normalizer architecture (verbatim source label → canonical slug, fail closed)
  and the deterministic tolerance layer.
- The five tools, the repositories, the three entities, the seed.
- The channel-agnostic seam and the WhatsApp adapter.
- Scorer buckets 1–5 in shape; the credit bands; the affiliation-dependent
  threshold.
- The `END`-sentinel routing discipline and its traversal tests.

## 10. What breaks, ordered by cost

1. **Graph topology** — 4 bundle nodes plus `_route_capacity` deleted; a project
   browsing sub-flow with back-navigation added; entry inverted. Largest item.
2. **Scorer budget** — Bucket 6 (15 pts) has no input; the `+8` bonus loses half
   its trigger; `gastos_mensuales` should feed a capacity ratio that does not
   exist. The six buckets no longer sum meaningfully to 100 and need re-budgeting
   against the v2 field set.
3. **Status domain** — `{ready, nurture, nurture_social}` →
   `{calificado, nutrible, no_calificado}`, touching the entity, the scorer, the
   tools, the specs and the 90/10 query.
4. **`otra_caja_compensacion`** — `String(60)` → `Boolean`, derived not asked;
   delete `CAJA_COMPENSACION` (43 entries) and the `pos_subsidio = 0` rule needs
   a home.
5. **Domain widenings** — `tipo_documento` 5 → 6, `contrato_laboral` 3 → 4.
6. **Two removed fields** and their columns, spec scenarios and derivations.

## 11. Immediate consequence for work in flight

`feat/whatsapp-interactive` (unmerged, see `PENDING.md`) builds a five-section
list menu for the 43 cajas de compensación. **v2 deletes that vocabulary**, so the
largest single piece of that branch becomes dead code. The webhook fix, the
renderer, the client methods and the text fallback all remain valuable. Re-scope
before merging.

## 12. Recommended sequence

Nothing here should be attempted before the jury delivery.

1. Get the two decisions recorded: is the affiliation question gated to
   non-affiliates (§5), and is age asked or derived (§6).
2. Resolve the column O / column P disagreement on `contrato_laboral` (§4).
3. Re-budget the scorer against the v2 field set before touching the graph —
   removing `antiguedad_laboral` without re-budgeting silently drops 15 points
   from every lead.
4. Then the topology: collapse the bundles first (pure deletion, lowest risk),
   then the entry inversion and the browsing loop (new surface, highest risk).
