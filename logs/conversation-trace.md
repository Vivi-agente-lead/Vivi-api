# Conversation trace — Vivi WhatsApp

Trace manual de los intercambios cliente ↔ bot. Cada fila es un turno. El
propósito es observar la respuesta del usuario junto con la pregunta exacta
que se le hizo, para detectar casos en que el parser determinista no acepta
una forma natural y el bot re-pregunta lo mismo.

Formato:

```
[TS] Q (node: <nodo>) | <texto que el bot mandó>
[TS] A (user: <wa_id>) | <texto que respondió el usuario>
[TS] ✗ rejected | <field>=<raw>  (cuando el parser no matchea)
[TS] ✓ accepted | <field>=<slug>
```

`TS` = timestamp tal cual lo trajo WhatsApp. `node` = nodo del StateGraph que
habló. `field` = clave del `lead_profile` en juego. `slug` = valor canónico
almacenado.

---

## Sesión 2026-07-26 — Frank probando el flujo (wa_id del bot: +57 318 1407198)

### Pregunta: rango_salarial

```
[06:08] Q (node: cap_*_sin_pareja o cap_*_con_pareja) | ¿En qué rango está tu salario mensual?
              - 2 millones o menos
              - 2 a 4 millones
              - 4 a 8 millones
              - 8 a 10 millones
              - mas de 10 millones
[06:08] A (user: Frank Urbina)              | 8 millones
[06:08] ✗ rejected                          | rango_salarial="8 millones"
                                                 → fold "8 millones" no está en
                                                   RANGO_SALARIAL={hasta_2m,2_4m,
                                                   4_8m,8_10m,mas_10m}. Parser
                                                   exacto, never guesses.
[06:08] Q (mismo nodo, re-ask)              | ¿En qué rango está tu salario mensual?
              - 2 millones o menos
              - 2 a 4 millones
              - 4 a 8 millones
              - 8 a 10 millones
              - mas de 10 millones
[06:08] A (user: Frank Urbina)              | Más de 10 millones
[06:08] ✓ accepted                          | rango_salarial="mas de 10 millones"
                                                 → fold "mas de 10 millones" →
                                                   match exacto → "mas_10m"
```

### Observación

El bot re-pregunta cuando el lead usa formas naturales ("8 millones" en vez
del verbatim "4 a 8 millones"). No es un defecto del LLM — el LLM solo
reformula la pregunta; la respuesta se valida con `validate_enumerated` →
`domain_normalizer.normalize`, que es match exacto por diseño (`Never guess`.
`_validators.py:6-8`). Eso protege auditoría pero tranca UX.

### Hipótesis de fix (a evaluar con el equipo)

- **A. Synonyms table**: agregar `{"8 millones": "4_8m", "3 millones": "2_4m",
  "10 millones": "8_10m", ...}` al normalizer. Sigue deterministic. 0 riesgo
  de alucinación. ~20 min.
- **B. LLM fallback** cuando el parser exacto falla: append 1 call al LLM con
  el menú y pedir elegí un slug o NONE. Más natural +latencia −auditoría.
- **C. Heurística numérica**: si la respuesta del usuario contiene dígitos,
  parsear el número y bucketearlo igual que `derive_rango_salarial`
  (`_validators.py:152-177`) hace con `salario_base_cotizacion`. El código
  ya tiene el prototipo; solo hay que aplicarlo al input textual del usuario.

Recomendado para hackathon: **C** porque ya existe el código prácticamente
dup, más **A** como fallback barato para los sinónimos más comunes.

---

## Sesión 2026-07-26 06:05–06:09 — WhatsApp end-to-end (bot → Frank Urbina)

Levantada de `vivi.messages` (34 filas, 1 conversación). Cada fila es un
turno real contra la API de Meta. Solo se anotan aquí los rechazos y los
aceptados ambiguos; las preguntas de ritmo simple se omiten.

```
[06:05] Q autorizacion_datos                         | ¡Hola! Soy Vivi…
[06:05] A "Si"                                       ✓ autorizacion=True
[06:05] Q tipo_documento                            | (5 opciones, CC/CE/PA/PEP/PPT)
[06:06] A "Cc"                                       ✓ tipo_documento=CC
                                                       (fold("cc") matches "cédula
                                                        de ciudadanía" → slug "CC"
                                                        en domain_normalizer)
[06:06] A "20896087"                                ✓ numero_documento="20896087"
[06:06] A "Frank urbina"                            ✓ nombre_apellido persistido
[06:06] A "16/07/1991"                              ✓ fecha_nacimiento → edad=35
[06:06] Q estado_civil                              | (6 opciones, sin acento en bullets)
[06:06] A "Casado"                                  ✓ casado
[06:07] Q otra_caja_compensacion                    | "Si no, responde Ninguna"
[06:07] A "Si"                                      ✗ no está en el vocabulario de
                                                       cajas. Bot re-pregunta.
[06:07] A "No"                                      ✓ parse_caja_compensacion("no")
                                                       → "ninguna"
[06:07] Q contrato_laboral                          | (3 opciones)
[06:07] A "Fijo"                                    ✗ fold("fijo") no está en
                                                       {termino_fijo,
                                                       termino_indefinido,
                                                       prestacion_servicios}. Bot
                                                       re-pregunta.
[06:07] A "Termino fijo"                            ✓ contrato_laboral=termino_fijo
                                                       → es_empleado=True
[06:07] Q cap_emp_con_pareja[0]: ingresos familiar | (parse_decimal)
[06:07] A "14 millones"                            ✓ total_ingresos_familiares
                                                       = 14_000_000
[06:08] Q antiguedad_laboral                        | (3 opciones; "Mas de dos años")
[06:08] A "Más de 2 años"                          ✗ fold="mas de 2 años" — el dígito
                                                       "2" no se normaliza a "dos".
                                                       Bot re-pregunta.
[06:08] A "Más de dos años"                        ✓ fold="mas de dos años" →
                                                       matches "Mas de dos años"
                                                       (línea 77 de slices.py) →
                                                       antiguedad_laboral=mas_2a
[06:08] Q rango_salarial                            | (5 opciones; "mas de 10 millones")
[06:08] A "8 millones"                              ✗ no hay opción que pliegue a
                                                       "8 millones" (solo "4 a 8
                                                       millones" o "8 a 10
                                                       millones"). Bot re-pregunta.
[06:08] A "Más de 10 millones"                      ✓ fold="mas de 10 millones" →
                                                       matches "mas de 10 millones"
                                                       (línea 72) → mas_10m
[06:09] Q tiene_vivienda_propia                     |
[06:09] A "Si"                                      ✓ (asumido; el bot avanzó a
                                                       ahorros_o_cesantias)
[06:09] Q ahorros_o_cesantias                       | (6 opciones; —
                                                       conversación cortada aquí)
```

### Hallazgos de la traza DB

- **Persist diferido**: la fila `leads` muestra `antiguedad_laboral`,
  `rango_salarial` y `total_ingresos_familiares_mensuales` en NULL aunque el
  bot ya avanzó past esos campos. Esto es por diseño — `collect()` en
  `_common.py:185-186` solo llama a `persist(profile, config, persist_fields)`
  cuando `_next_missing` es None (es decir, el bundle completo terminó). Los
  campos viven en el checkpointer in-memory; el `leads` row se actualiza
  recién cuando el bundle de capacity completa todos sus 11 fields.
- **`edad=35` ya persistido**: la derivación `derive edad(server-side) from
  fecha_nacimiento` fireó en `spine.py`. Frank tiene 35.
- **4 rechazos por forma natural** en 34 turnos (otra_caja, contrato_laboral,
  antiguedad, rango_salarial) — todos resueltos por el usuario repitiendo con
  el verbatim label. La tasa de rechazo es ~12% de los turnos coleccionables;
  llevaría a pérdida de leads en producción si no se agrega tolerance.

### Cédula 20896087 — análisis

- `afiliado_colsubsidio=False` (no está en la tabla sembrada de 15 afiliados
  demo; los seed son 1010101010, 2020202020, 3030303030 y 12 más).
- Con `estado_civil=casado` + `contrato_laboral=termino_fijo` el bundle
  asignado es `cap_emp_con_pareja` (empleado con pareja).
- `rango_salarial` se pregunta porque `_asks_rango_salarial` = True (es
  empleado AND no es afiliado).
- `otra_caja_compensacion=ninguna`, `mas de 10 millones` de salario
  individual, `14 millones` familiar — para el scorer esto se ve listo para
  `READY` una vez complete vivienda/ahorro/creditos/discapacidad/pac/subsidio.

### Pendientes (próximas observaciones a cargar)

- Verificar scoring final cuando Frank complete el bundle de capacity.
- Confirmar que `vis_recommended` se derive correctamente (ya está hecho
  para proyecto VIBO ONCE B2 cuando usuario dice Bogotá).
- Verificar el `score_credito` simulado por `simulate_bureau_cedula("20896087")`
  — debería ser determinístico vía SHA.

---

## Direcciones de mejora emergentes — input del user 2026-07-26

Tras ver la traza real + el system.py + whatsapp_client actuales, el user
levantó 3 defectos más profundos que elRechazo-del-parser:

### 1) Otra caja no se lista cuando el lead responde "Sí"

`otra_caja_compensacion` (`_validators.parse_caja_compensacion`) filtra por
el vocabulario `CAJA_COMPENSACION` (30+ entries) PERO el prompt en
`slices.py` solo dice "dime a cuál" sin listar opciones. El lead responde
"Sí" y el bot rebate — no era que iba a contestar con "Sí", sino que NO se
le dio el menú para empezar.

Fix: si el lead responde "sí", el siguiente turno debería listar las ≥30
cajas conocidas y dejarlo escoger. Pero 30 botones no caben en 3-button
interactive messages → requiere list messages (hasta 10 rows/section, hasta
10 sections — las 30+ cajas caben como 3 sections de 10).

### 2) WhatsApp Cloud API sí soporta selección táctil

Meta Cloud API tiene 4 tipos de mensajes `interactive` (verificados en
docs oficiales vía Context7/Kapso wrapper):

- `button` — **máximo 3 botones** (quick reply), cada uno con `id` + `title`
  (≤20 chars). El tap devuelve un `button_reply` webhook con el `id` elegido.
- `list` — hasta 10 secciones × 10 rows, cada row con `id` + `title` +
  `description`. Botón "Ver opciones" → menú desplegable. Tap devuelve
  `list_reply` webhook con el `id`.
- `cta_url` — 1 botón que abre URL (no aplica aquí).
- `single_select_message` — list con selección única, payload de vuelta.

NO hay checkbox multicheck nativo en WhatsApp Cloud API (apps de terceros
lo simulan con `list` + multiple taps pero el mensaje nativo es single
reply). Para `subsidio_vivienda_anterior`, `tiene_vivienda_propia`,
`tiene_creditos_activos`, `condicion_discapacidad_familiar` (todas
bool), el interactive button resolve: 2 botones "Sí" / "No" → payload
armado. Para `rango_salarial`, `antiguedad_laboral`, `ahorros_o_cesantias`,
`estado_civil`, `contrato_laboral`, `otra_caja`, `lugar_eleccion_vivir` →
list con rows. Cada row `id` = el slug canónico, `title` = el label humano.

**El webhook POST actual (`POST/whatsapp/webhook`) ya deserializa
`message.interactive.button_reply.id` y `list_reply.id`?** Falta verificar
— el `inbound_handler` probablemente solo parsee `message.text.body`. Si no
esta ruta, los tap reply llegarían como vacío y rompería el flujo. Es parte
del fix.

### 3) Las preguntas son robóticas — el LLM debe humanizar y el parser debe interpretar

Verificado en `app/prompts/system.py` (127 lines) y `_common.phrase()`
(líneas 226-272):

- El `SLICES[node]` que se inyecta en el system prompt NO es la pregunta que
  ve el lead. La pregunta base viene del dict `FIELD_QUESTIONS` en
  `slices.py` — escuetísima: "¿Cuál es tu estado civil?\n- Soltero\n- Casado\n…"
- El LLM solo hace UNA pasada para "reescribir" esa pregunta. La
  instrucción explícita (`_common.py:247-251`): *"Reescribe… conserva las
  opciones exactamente como están escritas, una por línea."* → el mísmo
  resultado复读. Las frases cálidas se ven en el trace ("¡Ya te voy
  conociendo mejor!") pero el esqueleto menu-planco sigue igual.
- Peor: las respuestas del usuario NUNCA ven al LLM. Van directo a
  `validate_enumerated` → exact fold lookup. Por eso "8 millones" rebota,
  "Fijo" rebota, "Más de 2 años" rebota (el dígito "2" no se mapea a "dos").

**El LLM está infrautilizado.** Lo pagás para que reformulee una pregunta
y nada más. Cuando la pregunta ya es buena, el coste del LLM es marginal.
Cuando el lead habla natural, lo único que asegurás es frustración.

### Diseño propuesto (3 capas)

**Capa 1 — WhatsApp interactive messages** (elimina "8 millones"
  re-preguntas): el bot envía una `list` con rows = slugs, el lead tapa una.
  No hay ambigüedad, no hay parser. Hit intermedio gratuito para el scorer.
  Adiccional: 30+ cajas entran como 3 secciones de 10 rows.

**Capa 2 — Interpretación con TOLERANCIA**: cuando el lead responde con
  texto libre (no tap, sino `text` body — lo que ocurre hoy), el flujo
  pregunta al LLM "mapea esta respuesta del humano al slug del menú, o None
  si no calza". Ejemplos: "8 millones" → `4_8m` o `8_10m`, "fijo" →
  `termino_fijo`, "dos años" → `1_2a` o `mas_2a`. Sigue habiendo auditoría
  si el LLM returns el slug pero la respuesta cruda se guarda en
  `normalization_notes`.

  Alternativa más económica para hackathon: regex numérico + tabla de
  sinónimos (option C del log anterior).

**Capa 3 — Humanización del prompt**:
   - El `FIELD_QUESTIONS` queda como plantilla base (la usa el sistema)
     PERO el system prompt para el LLM cambia de "reescribe manteniendo las
     opciones verbatim" a "tenés libertad de fraseo, mantenés el intent".
   - Si el LLM está configurado (demo Fly) el bot conversa con tono natural,
     confirma el dato anterior antes de ir a la siguiente pregunta ("Frank,
     te anotaste como casado y con contrato a término fijo. ¿Cuánto suman
     en ingresos tú y tu pareja?"), usa educación, recuerda el porqué.
   - Si no hay LLM, cae a la pregunta base escuetta (modo fallback,
     determinista para tests).

### Priorización sugerida para el hackathon (~horas restantes)

Riesgo/coste:
1. **Capa 1 (interactive messages)** — half-day de trabajo, resuelve los
   re-preguntas y la UX de seleccionar. 需要 actualizar whatsapp_client con
   `send_interactive_button`, `send_interactive_list`; el router webhook
   parsear `interactive.button_reply` / `list_reply`; el `collect()` usar
   `interactive` cuando un `Field` tiene `options`; la opción `.id` ir al
   parser como reply.
2. **Capa 2 (interpretación LLM)** — 1-2 horas. Reaprovecha existing
   `build_llm()`. Implementa `interpret_to_slug(reply, options)` en
   `domain_normalizer` o en validators. Llamás DESPUÉS de los sinónimos
   exactos — si exacto no matchea y hay LLM, mandás. Si no hay LLM,
   rechazás y re-preguntás (preserve behavior today).
3. **Capa 3 (humanización)** — 1 hora, solo prompt editing + tests on
   `prompt_slices` si needed. Cambiar system prompt slice para permitir
   natural fraseo, agregar una instrucción "conectá con la pregunta
   anterior —recordá el dato previo recolectado".