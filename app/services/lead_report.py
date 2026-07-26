"""Render a profiled lead as the report an asesor would receive by email.

The notification seam (`app/services/notifier.py`) deliberately sends nothing —
there is no mail transport in this project and faking one would be dishonest.
But a report nobody can read is not a deliverable either, so the same rendering
is served over HTTP: `GET /reporte` lists the profiled leads and
`GET /reporte/{documento}` shows one, exactly as it would arrive in an inbox.

Two rules shape what goes in it:

1. **Show the answer and its meaning.** A stored `4_8m` is meaningless to an
   asesor; the report shows "Entre $4 y $8 millones". Labels come from the same
   source workbook option lists the lead was shown, inverted through the
   normalizer, so the report can never drift from the vocabulary the bot used.
2. **Show the arithmetic.** `classification_reasoning` already carries the
   bucket-by-bucket breakdown the scorer produced. The report surfaces it
   verbatim rather than restating it, so what the asesor reads is what the
   scorer actually computed.

Pure module: no DB, no I/O, no template engine.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Iterable, Mapping

from app.prompts.slices import FIELD_OPTIONS
from app.services.domain_normalizer import normalize

__all__ = ["Report", "build_report", "render_text", "render_html", "render_inbox_html"]


# ── Slug → the words the person actually saw ───────────────────────────────
@lru_cache(maxsize=1)
def _slug_labels() -> dict[str, dict[str, str]]:
    """Invert every option list through the normalizer, once.

    `FIELD_OPTIONS` holds the verbatim source labels; `normalize` maps each to
    its canonical slug. Inverting gives slug → label without a second hardcoded
    table that could fall out of step with the workbook.
    """
    out: dict[str, dict[str, str]] = {}
    for field_name, options in FIELD_OPTIONS.items():
        pairs: dict[str, str] = {}
        for label in options:
            slug = normalize(field_name, label)
            if isinstance(slug, str):
                pairs[slug] = label
        if pairs:
            out[field_name] = pairs
    return out


_STATUS = {
    "calificado": ("Calificado", "Pasa al asesor comercial"),
    "nutrible": ("Nutrible", "Entra al flujo de nutrición"),
    "no_calificado": ("No calificado", "Cierre cordial, sin remisión"),
    "profiling": ("En perfilamiento", "Conversación aún en curso"),
}

_TIPO_DOC = {
    "CC": "Cédula de ciudadanía", "CE": "Cédula de extranjería", "PA": "Pasaporte",
    "PEP": "Permiso Especial de Permanencia", "PPT": "Permiso por Protección Temporal",
    "CD": "Carné Diplomático",
}


def _money(value: Any) -> str | None:
    """`4500000` → `$4.500.000`."""
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return "$" + f"{amount:,.0f}".replace(",", ".")


def _label(lead: Mapping[str, Any], key: str) -> str | None:
    """The human label for an enumerated field, or the raw value."""
    raw = lead.get(key)
    if raw is None:
        return None
    return _slug_labels().get(key, {}).get(str(raw), str(raw))


def _si_no(value: Any) -> str | None:
    if value is None:
        return None
    return "Sí" if value else "No"


@dataclass
class Section:
    titulo: str
    filas: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Report:
    titular: str
    documento: str
    estado: str
    estado_detalle: str
    accion: str
    score: int | None
    banda_credito: str | None
    secciones: list[Section]
    desglose: list[str]
    alertas: list[str]


def build_report(lead: Mapping[str, Any]) -> Report:
    """Everything the asesor needs, from one `leads` row."""
    estado_slug = str(lead.get("status") or "profiling")
    estado, accion = _STATUS.get(estado_slug, (estado_slug, ""))

    identidad = Section("Identificación")
    _add(identidad, "Nombre", lead.get("nombre_apellido"))
    _add(identidad, "Documento", f"{_TIPO_DOC.get(str(lead.get('tipo_documento')), lead.get('tipo_documento') or '')} {lead.get('numero_documento') or ''}".strip())
    _add(identidad, "Edad", f"{lead['edad']} años" if lead.get("edad") is not None else None)
    _add(identidad, "Estado civil", _label(lead, "estado_civil"))

    afiliacion = Section("Afiliación")
    _add(afiliacion, "Afiliado a Colsubsidio", _si_no(lead.get("afiliado_colsubsidio")))
    _add(afiliacion, "Categoría", lead.get("categoria"))
    _add(afiliacion, "Interés en afiliarse", _label(lead, "interes_afiliacion"))
    _add(afiliacion, "Afiliado a otra caja", _si_no(lead.get("otra_caja_compensacion")))

    capacidad = Section("Capacidad de compra")
    ingresos, gastos = lead.get("total_ingresos_mensuales"), lead.get("gastos_mensuales")
    _add(capacidad, "Ingresos del hogar", _money(ingresos))
    _add(capacidad, "Gastos del hogar", _money(gastos))
    if ingresos is not None and gastos is not None:
        try:
            disponible = Decimal(str(ingresos)) - Decimal(str(gastos))
            pct = (disponible / Decimal(str(ingresos)) * 100) if Decimal(str(ingresos)) > 0 else None
            texto = _money(disponible)
            if pct is not None:
                texto = f"{texto} ({pct:.0f}% de sus ingresos)"
            _add(capacidad, "Disponible al mes", texto)
        except (InvalidOperation, ValueError, ZeroDivisionError):
            pass
    _add(capacidad, "Rango salarial", _label(lead, "rango_salarial"))
    _add(capacidad, "Situación laboral", _label(lead, "contrato_laboral"))
    _add(capacidad, "Ahorros disponibles", _label(lead, "ahorros_o_cesantias"))
    _add(capacidad, "Personas a cargo", lead.get("numero_pac"))
    _add(capacidad, "Tiene vivienda propia", _si_no(lead.get("tiene_vivienda_propia")))
    _add(capacidad, "Recibió subsidio antes", _si_no(lead.get("subsidio_vivienda_anterior")))

    intencion = Section("Qué busca")
    _add(intencion, "Dónde quiere vivir", lead.get("lugar_eleccion_vivir"))
    _add(intencion, "Tipo de vivienda", _label(lead, "preferencia_vis"))
    _add(intencion, "Cuándo quiere comprar", _label(lead, "tiempo_compra_deseado"))
    _add(intencion, "En sus palabras", lead.get("descripcion_vivienda_sueno"))

    alertas: list[str] = []
    if lead.get("subsidio_vivienda_anterior"):
        alertas.append(
            "Ya recibió un subsidio de vivienda: no califica para uno nuevo, "
            "sin importar su puntaje."
        )
    if lead.get("otra_caja_compensacion"):
        alertas.append(
            "Está afiliado a otra caja de compensación: no puede acceder al "
            "subsidio de Colsubsidio."
        )
    if lead.get("tiene_vivienda_propia") and lead.get("vis_recommended"):
        alertas.append("Ya tiene vivienda propia y busca VIS — revisar elegibilidad.")

    desglose = [
        line.strip()
        for line in str(lead.get("classification_reasoning") or "").splitlines()
        if line.strip()
    ]

    return Report(
        titular=str(lead.get("nombre_apellido") or lead.get("numero_documento") or "Lead sin nombre"),
        documento=str(lead.get("numero_documento") or ""),
        estado=estado,
        estado_detalle=estado_slug,
        accion=accion,
        score=lead.get("score"),
        banda_credito=lead.get("score_rating"),
        secciones=[s for s in (identidad, afiliacion, capacidad, intencion) if s.filas],
        desglose=desglose,
        alertas=alertas,
    )


def _add(section: Section, etiqueta: str, valor: Any) -> None:
    """Append a row, skipping anything the lead never answered."""
    if valor is None or valor == "":
        return
    section.filas.append((etiqueta, str(valor)))


# ── Plain text: this is the email body ─────────────────────────────────────
def render_text(report: Report) -> str:
    out = [
        f"{report.estado.upper()} — {report.titular}",
        f"Puntaje: {report.score if report.score is not None else 's/d'}/100"
        + (f"  ·  Banda crediticia: {report.banda_credito}" if report.banda_credito else ""),
        f"Acción: {report.accion}",
    ]
    for alerta in report.alertas:
        out.append(f"[!] {alerta}")
    for seccion in report.secciones:
        out.append("")
        out.append(seccion.titulo.upper())
        out += [f"  {k}: {v}" for k, v in seccion.filas]
    if report.desglose:
        out.append("")
        out.append("CÓMO SE CALCULÓ")
        out += [f"  {line}" for line in report.desglose]
    return "\n".join(out)


# ── HTML: the same report, for the browser ─────────────────────────────────
_CSS = """
:root{--ink:#1a1a1a;--muted:#6b7280;--line:#e5e7eb;--bg:#f6f7f9}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--ink);
 font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:720px;margin:0 auto}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;
 padding:1.75rem;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:1rem}
.from{color:var(--muted);font-size:.85rem;border-bottom:1px solid var(--line);
 padding-bottom:.9rem;margin-bottom:1.25rem}
h1{font-size:1.5rem;margin:0 0 .3rem}
.badge{display:inline-block;padding:.28rem .8rem;border-radius:999px;
 font-size:.8rem;font-weight:600;letter-spacing:.02em}
.calificado{background:#dcfce7;color:#166534}
.nutrible{background:#fef3c7;color:#92400e}
.no_calificado{background:#f1f5f9;color:#475569}
.profiling{background:#e0e7ff;color:#3730a3}
.score{font-size:2.6rem;font-weight:700;line-height:1}
.score small{font-size:1rem;font-weight:400;color:var(--muted)}
.accion{color:var(--muted);margin:.35rem 0 0}
.alert{background:#fef2f2;border-left:3px solid #dc2626;color:#991b1b;
 padding:.7rem .9rem;border-radius:6px;margin:.5rem 0;font-size:.92rem}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;
 color:var(--muted);margin:1.75rem 0 .6rem}
table{width:100%;border-collapse:collapse}
td{padding:.5rem 0;border-bottom:1px solid var(--line);vertical-align:top}
td:first-child{color:var(--muted);width:45%}
td:last-child{font-weight:500}
pre{background:#f8fafc;border:1px solid var(--line);border-radius:8px;
 padding:.9rem 1rem;font-size:.87rem;overflow-x:auto;white-space:pre-wrap;margin:0}
a{color:#1d4ed8;text-decoration:none}
.list li{list-style:none;border-bottom:1px solid var(--line);padding:.85rem 0;
 display:flex;justify-content:space-between;align-items:center;gap:1rem}
.list{margin:0;padding:0}
.muted{color:var(--muted);font-size:.87rem}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )


def render_html(report: Report) -> str:
    """One lead, laid out as the email the asesor receives."""
    e = html.escape
    parts = [
        "<div class='card'>",
        "<div class='from'><b>Para:</b> asesor.comercial@colsubsidio.com &nbsp;·&nbsp; "
        "<b>De:</b> Vivi &lt;no-reply@vivi&gt;<br>"
        f"<b>Asunto:</b> Lead {e(report.estado.lower())}: {e(report.titular)}</div>",
        f"<span class='badge {e(report.estado_detalle)}'>{e(report.estado)}</span>",
        f"<h1>{e(report.titular)}</h1>",
        f"<p class='accion'>{e(report.accion)}</p>",
    ]
    if report.score is not None:
        banda = f" <small>· {e(str(report.banda_credito))}</small>" if report.banda_credito else ""
        parts.append(f"<p class='score'>{report.score}<small>/100</small>{banda}</p>")
    parts += [f"<div class='alert'>{e(a)}</div>" for a in report.alertas]

    for seccion in report.secciones:
        parts.append(f"<h2>{e(seccion.titulo)}</h2><table>")
        parts += [f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in seccion.filas]
        parts.append("</table>")

    if report.desglose:
        parts.append("<h2>Cómo se calculó este puntaje</h2><pre>")
        parts.append(e("\n".join(report.desglose)))
        parts.append("</pre>")

    parts.append("<p class='muted' style='margin-top:1.5rem'>"
                 "Este es el correo que recibiría el asesor. No se envía: no hay "
                 "transporte de correo configurado, se muestra tal cual se generaría."
                 "</p>")
    parts.append("</div><p class='muted'><a href='/reporte'>← Volver a la bandeja</a></p>")
    return _page(f"{report.titular} — {report.estado}", "".join(parts))


def render_inbox_html(reports: Iterable[tuple[str, Report]]) -> str:
    """The list of profiled leads — the asesor's inbox."""
    e = html.escape
    items = []
    for documento, r in reports:
        score = f"{r.score}/100" if r.score is not None else "—"
        items.append(
            f"<li><span><b>{e(r.titular)}</b><br>"
            f"<span class='muted'>{e(documento)}</span></span>"
            f"<span style='text-align:right'>"
            f"<span class='badge {e(r.estado_detalle)}'>{e(r.estado)}</span><br>"
            f"<span class='muted'>{e(score)}</span></span>"
            f"<a href='/reporte/{e(documento)}'>Ver →</a></li>"
        )
    cuerpo = (
        "<div class='card'><h1>Leads perfilados</h1>"
        "<p class='muted'>Cada uno es un correo que recibiría el asesor comercial. "
        "Nada se envía — se muestra el contenido tal cual se generaría.</p>"
        + (f"<ul class='list'>{''.join(items)}</ul>" if items
           else "<p class='muted'>Todavía no hay leads perfilados. "
                "Conversa con Vivi por WhatsApp y vuelve a esta página.</p>")
        + "</div>"
    )
    return _page("Leads perfilados — Vivi", cuerpo)
