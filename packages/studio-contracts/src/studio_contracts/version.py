from __future__ import annotations

from pydantic import BaseModel, Field

CLIENT_FAMILIES: tuple[str, ...] = ("desktop", "daemon", "dashboard")

CLIENT_HEADER = "X-Studio-Client"
VERSION_HEADER = "X-Studio-Client-Version"
UPDATE_HEADER = "X-Studio-Client-Update"
LATEST_HEADER = "X-Studio-Client-Latest"

CLIENT_STATUS_CURRENT = "current"
CLIENT_STATUS_RECOMMENDED = "recommended"


class VersionInfo(BaseModel):
    api_version: str = Field(description="API contract major version.")
    server_version: str = Field(description="Running server build version.")
    minimum_supported: dict[str, str] = Field(
        description="Oldest client build per family the server still serves."
    )
    latest: dict[str, str] = Field(description="Newest known client build per family.")


class ClientUpgradeRequired(BaseModel):
    error_code: str = Field(default="client_upgrade_required")
    client: str
    client_version: str
    minimum_supported: str
    latest: str
    message: str = Field(
        default="This client version is no longer supported. Please update to the latest release."
    )
