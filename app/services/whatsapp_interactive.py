"""Meta Cloud API `interactive` message shapes, built from field options.

This is the ONE place that knows the Meta Cloud API's `interactive` limits
(button count, title/description lengths, list section/row caps). It turns
the channel-agnostic `(field, options)` pair the graph hands out — see
`app.graph.nodes._common._interactive_kwargs` — into the button/list payload
fragments `WhatsAppClient` sends. `app/graph/**` never imports this module;
this module may freely import from `app.services.domain_normalizer` because
that dependency runs the other way (adapter depending on a domain service),
which is what the Channel-Agnostic Boundary requirement constrains.

Pure and side-effect free: no HTTP, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.domain_normalizer import normalize

__all__ = [
    "MAX_BUTTONS",
    "MAX_BUTTON_TITLE",
    "MAX_ROW_TITLE",
    "MAX_ROW_DESCRIPTION",
    "MAX_SECTION_TITLE",
    "MAX_ROWS_PER_SECTION",
    "MAX_SECTIONS",
    "MAX_LIST_OPTIONS",
    "InteractiveButtons",
    "InteractiveList",
    "render_options",
]

# ── Meta Cloud API `interactive` message limits ─────────────────────────────
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72
MAX_SECTION_TITLE = 24
MAX_ROWS_PER_SECTION = 10
MAX_SECTIONS = 10
MAX_LIST_OPTIONS = MAX_ROWS_PER_SECTION * MAX_SECTIONS


@dataclass(frozen=True)
class InteractiveButtons:
    """Payload fragment for `interactive.type == "button"` (<=3 options)."""

    buttons: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class InteractiveList:
    """Payload fragment for `interactive.type == "list"` (4+ options)."""

    button_text: str
    sections: tuple[dict[str, object], ...]


def render_options(
    field: str, options: Sequence[str]
) -> InteractiveButtons | InteractiveList | None:
    """Pick the tactile shape for `options`, or `None` when nothing fits.

    - <=3 options AND every label <=20 chars -> quick-reply buttons (Meta
      buttons have no separate description field, so a label that does not
      fit the title is not offered as a button at all — it falls through to
      the list branch below instead of being silently truncated into
      something the person did not actually see).
    - 1..100 options -> a list, rows chunked into <=10-row sections. Row
      titles are truncated to 24 chars, but the full label always survives in
      the row `description` (<=72 chars), so nothing legible is lost even for
      the two `tipo_documento` labels over 24 chars ("Permiso especial de
      permanencia", "Permiso por protección temporal").
    - More than 100 options, or an empty option set -> `None`. The caller
      (`InboundMessageHandler`) degrades to plain text in both cases, and
      whenever the interactive send itself fails.

    Row/button `id`s are the canonical slug when `domain_normalizer.normalize`
    knows one for `field` (e.g. `4_8m`, `termino_fijo`), so a tap arrives at
    the existing deterministic parser with zero interpretation. Fields with no
    slug table (`lugar_eleccion_vivir`) fall back to the verbatim label, which
    `validate_municipio` already accepts as-is.
    """
    cleaned = [o for o in options if o]
    if not cleaned:
        return None

    if len(cleaned) <= MAX_BUTTONS and all(len(o) <= MAX_BUTTON_TITLE for o in cleaned):
        buttons = tuple(
            {"type": "reply", "reply": {"id": _option_id(field, o), "title": o}}
            for o in cleaned
        )
        return InteractiveButtons(buttons=buttons)

    if len(cleaned) > MAX_LIST_OPTIONS:
        return None

    sections: list[dict[str, object]] = []
    chunked = len(cleaned) > MAX_ROWS_PER_SECTION
    for index, start in enumerate(range(0, len(cleaned), MAX_ROWS_PER_SECTION), start=1):
        chunk = cleaned[start : start + MAX_ROWS_PER_SECTION]
        rows = tuple(_row(field, o) for o in chunk)
        title = f"Opciones {index}" if chunked else "Opciones"
        sections.append({"title": _truncate(title, MAX_SECTION_TITLE), "rows": rows})
    return InteractiveList(button_text="Ver opciones", sections=tuple(sections))


def _row(field: str, label: str) -> dict[str, str]:
    """One list row: id, title, and a description **only when it adds something**.

    WhatsApp renders the description on its own line under the title, so setting
    both to the same text makes every option appear twice in the menu. The
    description therefore carries the full label only when the title had to be
    truncated to fit `MAX_ROW_TITLE` — which is the one case where the person
    would otherwise not see the whole option.
    """
    title = _truncate(label, MAX_ROW_TITLE)
    row = {"id": _option_id(field, label), "title": title}
    if title != label:
        row["description"] = _truncate(label, MAX_ROW_DESCRIPTION)
    return row


def _option_id(field: str, label: str) -> str:
    """The canonical slug for `label`, or `label` itself when there is none."""
    slug = normalize(field, label)
    return slug if isinstance(slug, str) else label


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"
