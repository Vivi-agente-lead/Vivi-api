"""Block C — the outbound notification seam (`app/services/notifier.py`).

No mail transport exists in this project: `LoggingNotifier` only logs what it
would send. These tests assert the seam is exercised, never that mail was
delivered.
"""

from __future__ import annotations

from app.services.notifier import LoggingNotifier, notify_lead_qualified


async def test_logging_notifier_records_the_would_be_email_without_sending() -> None:
    notifier = LoggingNotifier()
    profile = {
        "nombre_apellido": "Andrea Marín",
        "tipo_documento": "CC",
        "numero_documento": "1010101010",
        "score": 88,
        "score_rating": "Excelente",
        "municipio_normalizado": "Bogota",
    }

    await notify_lead_qualified(
        profile, quiere_asesor_credito=True, notifier=notifier
    )

    assert len(notifier.sent) == 1
    record = notifier.sent[0]
    assert "Andrea Marín" in record["subject"]
    assert "1010101010" in record["body"]
    assert record["context"]["quiere_asesor_credito"] is True


async def test_logging_notifier_does_not_require_a_credit_advisor_answer() -> None:
    """The v2 diagram draws no branch on the credit-advisor answer — the
    notification fires regardless of `Sí`/`No`/unanswered."""
    notifier = LoggingNotifier()

    await notify_lead_qualified(
        {"numero_documento": "555"}, quiere_asesor_credito=None, notifier=notifier
    )

    assert len(notifier.sent) == 1
    assert notifier.sent[0]["context"]["quiere_asesor_credito"] is None
