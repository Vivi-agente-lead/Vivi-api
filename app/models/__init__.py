"""SQLAlchemy ORM entities for vivi-api.

`LeadEntity` is kept as a backward-compat alias for `LeadColsubsidioEntity`
(`app/models/lead_model.py`) so legacy imports keep resolving until Phase 5
rewrites the tool surface.
"""

from app.models.afiliado_model import AfiliadoColsubsidioEntity
from app.models.base import Base
from app.models.conversation_model import ConversationEntity
from app.models.lead_model import LeadColsubsidioEntity, LeadEntity
from app.models.message_model import MessageEntity
from app.models.proyecto_model import ProyectoColsubsidioEntity

__all__ = [
    "Base",
    "ConversationEntity",
    "LeadColsubsidioEntity",
    "LeadEntity",  # backward-compat alias; Phase 5 removes it
    "MessageEntity",
    "AfiliadoColsubsidioEntity",
    "ProyectoColsubsidioEntity",
]