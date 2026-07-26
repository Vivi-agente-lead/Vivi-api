"""Outbound notification seam (Block C, `docs/v2-impact-analysis.md` §7-§8).

No mail transport exists anywhere in this project. `Enviar notificación por
correo` in the v2 flow diagram is implemented here as a clean seam whose
default implementation only **logs** what it would send — it does not send
anything. This is deliberate: faking a delivered email would be dishonest
about what the system does, and adding an SMTP/API dependency is out of scope
for this work unit.

Swap `get_notifier()`'s default `LoggingNotifier` for a real implementation
(SMTP, SES, Postmark, …) the day this project actually integrates a mail
provider; nothing upstream of this module needs to change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

__all__ = ["Notifier", "LoggingNotifier", "get_notifier", "notify_lead_qualified"]


class Notifier(Protocol):
    """The seam Block C's graph nodes depend on — never a concrete transport."""

    async def send(self, *, subject: str, body: str, context: dict[str, Any]) -> None: ...


@dataclass
class LoggingNotifier:
    """Default `Notifier`: logs the would-be email, sends nothing.

    `sent` records every call so tests can assert a notification was raised
    without asserting mail was delivered — because it wasn't.
    """

    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(self, *, subject: str, body: str, context: dict[str, Any]) -> None:
        self.sent.append({"subject": subject, "body": body, "context": dict(context)})
        logger.info(
            "notifier.would_send_email",
            extra={"subject": subject, "context_keys": sorted(context)},
        )


_default_notifier: Notifier = LoggingNotifier()


def get_notifier() -> Notifier:
    """The process-wide notifier. Tests may pass their own via `notifier=`."""
    return _default_notifier


async def notify_lead_qualified(
    profile: dict[str, Any],
    *,
    quiere_asesor_credito: bool | None,
    notifier: Notifier | None = None,
) -> None:
    """Log the "lead calificado" notification a real mail integration would send.

    Args:
        profile: the lead's working copy (`lead_profile`).
        quiere_asesor_credito: the lead's answer to
            `¿Te conecto con un asesor de crédito?`.
        notifier: override for tests; defaults to `get_notifier()`.
    """
    notifier = notifier or get_notifier()
    nombre = profile.get("nombre_apellido") or profile.get("numero_documento") or "sin nombre"
    subject = f"Lead calificado: {nombre}"
    # The same render the `/reporte` pages serve, so what an asesor would read
    # in the inbox and what a juror opens in the browser cannot drift apart.
    from app.services.lead_report import build_report, render_text

    body = render_text(build_report(profile))
    if quiere_asesor_credito is not None:
        body += (
            "\n\nASESOR DE CRÉDITO\n  "
            + ("Solicitó que lo contacten." if quiere_asesor_credito
               else "No solicitó asesoría de crédito.")
        )
    body += (
        f"\n\nPerfil completo: /reporte/{profile.get('numero_documento') or ''}"
    )
    await notifier.send(
        subject=subject,
        body=body,
        context={
            "numero_documento": profile.get("numero_documento"),
            "status": profile.get("status"),
            "quiere_asesor_credito": quiere_asesor_credito,
        },
    )
