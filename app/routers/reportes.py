"""Read-only view of the profiled leads — the report an asesor would receive.

`app/services/notifier.py` deliberately sends no mail: there is no transport in
this project and faking a delivery would be dishonest. But the point of the
notification is the *content* — the collected answers, digested and scored — and
content nobody can open is not a deliverable.

So the same render the notifier logs is also served here:

- `GET /reporte` — the inbox: every profiled lead, newest first.
- `GET /reporte/{numero_documento}` — one lead, laid out as the email.

Read-only by construction: no route in this module writes anything.

> **Demo surface.** These pages show lead data without authentication, which is
> acceptable here because every afiliado and every credit score in this build is
> fabricated (see the README). A real deployment must put them behind auth.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.core.db import async_session_maker
from app.models.lead_model import LeadColsubsidioEntity
from app.services.lead_report import (
    build_report,
    render_html,
    render_inbox_html,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reporte", tags=["reporte"])

# The inbox is a demo view, not a paginated console.
_MAX_ROWS = 50


def _as_dict(lead: LeadColsubsidioEntity) -> dict:
    """The ORM row as the plain mapping `build_report` expects."""
    return {
        column.name: getattr(lead, column.name)
        for column in lead.__table__.columns
    }


@router.get("", response_class=HTMLResponse)
async def bandeja() -> HTMLResponse:
    """Every profiled lead, newest first."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(LeadColsubsidioEntity)
            .where(LeadColsubsidioEntity.deleted_at.is_(None))
            .order_by(LeadColsubsidioEntity.updated_at.desc())
            .limit(_MAX_ROWS)
        )
        leads = result.scalars().all()

    reports = [
        (lead.numero_documento or "", build_report(_as_dict(lead))) for lead in leads
    ]
    return HTMLResponse(render_inbox_html(reports))


@router.get("/{numero_documento}", response_class=HTMLResponse)
async def detalle(numero_documento: str) -> HTMLResponse:
    """One lead, laid out as the email the asesor receives.

    Looks up by document number rather than by row id so the URL is something a
    person can type from the conversation they just had.
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(LeadColsubsidioEntity)
            .where(
                LeadColsubsidioEntity.numero_documento == numero_documento,
                LeadColsubsidioEntity.deleted_at.is_(None),
            )
            .order_by(LeadColsubsidioEntity.updated_at.desc())
            .limit(1)
        )
        lead = result.scalars().first()

    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay ningún lead perfilado con el documento {numero_documento}.",
        )
    return HTMLResponse(render_html(build_report(_as_dict(lead))))
