# Guía técnica

Setup, simulador, despliegue y verificación. Para el resumen del producto ver el
[README](../README.md); para las decisiones de diseño, [ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Stack

Python 3.12 · FastAPI · LangGraph · LangChain + OpenAI · SQLAlchemy 2 async ·
PostgreSQL · WhatsApp Cloud API.

Versiones exactas en `pyproject.toml` y `requirements.lock`.

## Correr en local

```bash
cp .env.example .env          # completa OPENAI_API_KEY
pip install -e ".[dev]"
```

El flujo de base de datos es: **crear la base → levantar la API (crea las
tablas) → sembrar los datos**.

```bash
python -m scripts.bootstrap_db        # crea el esquema, idempotente, sin DROP
python -m scripts.seed_colsubsidio    # 44 proyectos + 15 afiliados de demo
uvicorn app.main:app --reload
```

Para regenerar desde cero: `python -m scripts.reset_db --yes`. Es el único
comando destructivo del proyecto — ni el arranque de la API ni el seed borran
nada.

## Probar la conversación sin WhatsApp

`POST /whatsapp/simulate` recorre el pipeline completo (grafo, tools,
persistencia) sin llamar a Meta. Solo existe cuando `APP_ENV=development`.

```bash
curl -X POST "http://localhost:8000/whatsapp/simulate" --get \
  --data-urlencode "from=573001234567" \
  --data-urlencode "text=Hola" \
  --data-urlencode "dry_run=true"
```

Repite con cada respuesta reusando el mismo `from` para continuar el mismo hilo.
Con `dry_run=true` la respuesta del agente vuelve en el cuerpo y no se envía nada
a Meta.

> El simulador es solo texto: los botones y listas se envían únicamente por
> WhatsApp real. El menú se responde escribiendo la opción.

## Verificar el webhook

```bash
curl -i "http://localhost:8000/whatsapp/webhook?hub.mode=subscribe\
&hub.verify_token=$WHATSAPP_WEBHOOK_VERIFY_TOKEN&hub.challenge=12345"
```

Devuelve `12345` con 200 si el token coincide, 403 si no. Es el mismo chequeo
que corre Meta contra la URL desplegada.

`POST /whatsapp/webhook` valida `X-Hub-Signature-256` contra
`WHATSAPP_APP_SECRET`. Una firma ausente o inválida responde 403 sin crear
conversación ni llamar al modelo. Con el secreto vacío la verificación se omite
**solo** en `development`.

## Tests

```bash
pytest -q
```

354 tests. Los 3 que aparecen como `skipped` son los de idempotencia del seed:
requieren un PostgreSQL accesible y se saltan solos cuando no lo hay.

## Salud del servicio

`GET /health` responde 503 nombrando la dependencia cuando la base no está
disponible, y 200 solo cuando el esquema se creó bien. No es una prueba de vida
a secas: si `init_db()` falla, el endpoint lo dice en lugar de responder 200 con
la base vacía.

## Desplegar en Fly.io

La región es US para evitar el bloqueo geográfico de OpenAI.

```bash
fly launch --no-deploy            # usa el fly.toml del repo
fly secrets set \
  OPENAI_API_KEY=... \
  POSTGRES_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=vivi \
  WHATSAPP_API_TOKEN=... WHATSAPP_PHONE_NUMBER_ID=... \
  WHATSAPP_WEBHOOK_VERIFY_TOKEN=... WHATSAPP_APP_SECRET=...
fly deploy
```

Después del primer despliegue, sembrar una vez:

```bash
fly ssh console -C "python -m scripts.bootstrap_db"
fly ssh console -C "python -m scripts.seed_colsubsidio"
```

Con `APP_ENV=production` el simulador deja de registrarse: `/whatsapp/simulate`
responde 404. Es intencional — con `dry_run=false` sería un relay abierto capaz
de enviar mensajes a cualquier número con las credenciales del proyecto.

Por último, apuntar el webhook de Meta a
`https://<app>.fly.dev/whatsapp/webhook` con el mismo verify token.

## Consultas útiles

Proporción de afiliados entre los leads calificados — el objetivo 90/10 del reto:

```sql
SELECT
  count(*) FILTER (WHERE afiliado_colsubsidio)     AS afiliados,
  count(*) FILTER (WHERE NOT afiliado_colsubsidio) AS no_afiliados,
  round(100.0 * count(*) FILTER (WHERE afiliado_colsubsidio)
        / NULLIF(count(*), 0), 1)                  AS pct_afiliados
FROM leads
WHERE status = 'calificado';
```

Cómo se calificó un lead concreto:

```sql
SELECT numero_documento, status, score, score_rating, classification_reasoning
FROM leads
ORDER BY updated_at DESC
LIMIT 5;
```

`classification_reasoning` trae el desglose bucket por bucket, incluida la línea
del subsidio previo y la de `pos_subsidio` cuando aplican.

## Límites conocidos

**Datos simulados.** Los 15 afiliados y su historial crediticio son inventados
para la demo. Los 44 proyectos sí son transcripción literal del catálogo real.
Para un no afiliado el score de crédito se simula de forma determinista a partir
de la cédula, y queda etiquetado como *simulado* en el motivo de la
clasificación.

**Meta en modo sandbox.** Una app de WhatsApp Business en desarrollo solo entrega
mensajes a los números agregados como testers en el panel de Meta. Con cualquier
otro número el envío falla en silencio. El simulador evita esto por completo.

**Sin Alembic.** El esquema se crea con `create_all`. Para producción hace falta
migraciones reales.

**Sin aprobación humana previa.** `save_lead` escribe directo, sin paso de
confirmación.

**El correo al asesor no se envía.** `app/services/notifier.py` es una costura
limpia cuya implementación por defecto registra en el log lo que enviaría. No
hay transporte SMTP en el proyecto.

**Sin canal web.** `AgentService.stream_message` y los esquemas SSE existen en el
código y comparten la costura agnóstica de canal, pero ningún router los expone.
WhatsApp es el único canal montado.

Lo que quedó pendiente y por qué está en [`PENDING.md`](../PENDING.md).
