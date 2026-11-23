"""Import every model so `Base.metadata` is complete for Alembic autogenerate."""

from studio_api.db.models.account_token import AccountTokenModel
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.base import Base
from studio_api.db.models.break_glass import (
    BreakGlassAuditModel,
    BreakGlassRequestModel,
)
from studio_api.db.models.budget import BudgetPolicyModel, BudgetReservationModel
from studio_api.db.models.build import BuildModel, GitHubIntegrationModel, ProducerJobModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.execution_snapshot import ExecutionSnapshotModel
from studio_api.db.models.idempotency import IdempotencyKeyModel
from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.models.launch_credential import LaunchCredentialModel
from studio_api.db.models.library import (
    LibraryProjectLockModel,
    LibraryResourceLinkModel,
    LibraryResourceModel,
    LibraryResourceVersionModel,
)
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.machine_launch_grant import MachineLaunchGrantModel
from studio_api.db.models.plan import PlanLimitModel, PlanModel, StudioPlanCounterModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.project_repository import ProjectRepositoryModel
from studio_api.db.models.refresh_token import RefreshTokenModel
from studio_api.db.models.roadmap import (
    RoadmapModel,
    RoadmapPhaseModel,
    RoadmapRevisionModel,
    RoadmapStepDependencyModel,
    RoadmapStepModel,
    RoadmapStepTaskLinkModel,
)
from studio_api.db.models.runtime import RuntimeBindingModel, RuntimeModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.studio_export import StudioExportModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.usage import (
    UsageLedgerEntryModel,
    UsagePriceListModel,
    UsageSubscriptionModel,
)
from studio_api.db.models.user import UserModel
from studio_api.db.models.vault import VaultNoteLinkModel, VaultNoteModel, VaultNoteVersionModel
from studio_api.db.models.work_session import WorkSessionModel

__all__ = [
    "LaunchCredentialModel",
    "Base",
    "UserModel",
    "BreakGlassRequestModel",
    "BreakGlassAuditModel",
    "AccountTokenModel",
    "RefreshTokenModel",
    "MachineModel",
    "AgentModel",
    "ProjectModel",
    "StudioModel",
    "StudioMembershipModel",
    "PlanModel",
    "PlanLimitModel",
    "StudioPlanCounterModel",
    "StudioExportModel",
    "MachineLaunchGrantModel",
    "ProjectMembershipModel",
    "ProjectRepositoryModel",
    "TaskModel",
    "TaskLaunchModel",
    "WorkSessionModel",
    "UsageLedgerEntryModel",
    "UsagePriceListModel",
    "UsageSubscriptionModel",
    "ExecutionSnapshotModel",
    "BudgetPolicyModel",
    "BudgetReservationModel",
    "VaultNoteModel",
    "VaultNoteLinkModel",
    "VaultNoteVersionModel",
    "ResourceClaimModel",
    "DecisionModel",
    "AIWorkLogModel",
    "BuildModel",
    "GitHubIntegrationModel",
    "ProducerJobModel",
    "EventModel",
    "LibraryResourceModel",
    "LibraryResourceVersionModel",
    "LibraryResourceLinkModel",
    "LibraryProjectLockModel",
    "RuntimeBindingModel",
    "RuntimeModel",
    "RoadmapModel",
    "RoadmapPhaseModel",
    "RoadmapStepModel",
    "RoadmapStepDependencyModel",
    "RoadmapStepTaskLinkModel",
    "RoadmapRevisionModel",
    "TransferModel",
    "IdempotencyKeyModel",
    "InfraMeasurementModel",
]
