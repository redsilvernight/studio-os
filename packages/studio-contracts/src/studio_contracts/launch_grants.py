from __future__ import annotations

from datetime import datetime
from uuid import UUID

from studio_contracts.common import ContractModel


class MachineLaunchGrantCreate(ContractModel):
    """Body of `PUT /machines/{machine_id}/launch-grants/{user_id}`. Both
    bounds are optional: no `project_id` = any project the grantee is a
    member of, no `expires_at` = until revoked."""

    project_id: UUID | None = None
    expires_at: datetime | None = None


class MachineLaunchGrant(ContractModel):
    """Right, given by a machine's owner (AIB-J), for another User to launch
    work on that machine. Granted or removed, never modified — hence no
    `version`. It never widens project access: the grantee must also be a
    member of the task's project."""

    machine_id: UUID
    user_id: UUID
    project_id: UUID | None = None
    expires_at: datetime | None = None
    granted_by_user_id: UUID
    created_at: datetime
