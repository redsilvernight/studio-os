"""Import every model so `Base.metadata` is complete for Alembic autogenerate."""

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.base import Base
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.idempotency import IdempotencyKeyModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel

__all__ = [
    "Base",
    "UserModel",
    "MachineModel",
    "AgentModel",
    "ProjectModel",
    "TaskModel",
    "WorkSessionModel",
    "ResourceClaimModel",
    "DecisionModel",
    "AIWorkLogModel",
    "EventModel",
    "TransferModel",
    "IdempotencyKeyModel",
]
