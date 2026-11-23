from __future__ import annotations

import uuid
from datetime import UTC, datetime

from studio_operator.repository import ProtectedStudioError
from studio_operator.schemas import (
    Alert,
    CostTotal,
    Dashboard,
    ServiceHealth,
    StorageUsage,
    StudioDetail,
    StudioSummary,
    StudioUsageRow,
    SuspendedStudio,
    UsageReport,
    UsageTotals,
)

EMPTY = uuid.UUID("00000000-0000-0000-0000-000000000001")
ATELIER = uuid.UUID("11111111-1111-1111-1111-111111111111")
BINAWEB = uuid.UUID("22222222-2222-2222-2222-222222222222")
INTERNAL = uuid.UUID("00000000-0000-0000-0000-0000000000ff")


def _summary(
    studio_id: uuid.UUID,
    name: str,
    *,
    plan: str = "free",
    status: str = "active",
    used: int = 0,
    quota: int | None = None,
    members: int = 1,
    members_limit: int | None = 5,
    owner: str | None = "flo@example.test",
    suspension_reason: str | None = None,
) -> StudioSummary:
    return StudioSummary(
        id=studio_id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        plan=plan,
        status=status,
        suspension_reason=suspension_reason,
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        owner_email=owner,
        storage=StorageUsage(
            used_bytes=used,
            quota_bytes=quota,
            percent=None if not quota else round(used * 100.0 / quota, 1),
        ),
        members=members,
        members_limit=members_limit,
    )


STUDIOS = [
    _summary(ATELIER, "Atelier Phare", used=1_932_735_283, quota=2 * 1024**3, members=3),
    _summary(
        BINAWEB,
        "Binaweb",
        plan="pro",
        used=44_040_192_000,
        quota=100 * 1024**3,
        members=9,
        members_limit=25,
    ),
    _summary(
        INTERNAL,
        "Studio OS",
        status="suspended",
        suspension_reason="Impayé depuis 21 jours",
        used=1024**3,
        quota=2 * 1024**3,
        owner="ops@example.test",
    ),
]


class FakeRepository:
    """In-memory stand-in for the SQL repository (no PostgreSQL needed)."""

    def __init__(self) -> None:
        self.studios = list(STUDIOS)
        self.writes: list[tuple[uuid.UUID, str, str | None]] = []
        self.queries: list[str | None] = []
        self.days: list[int] = []

    async def list_studios(self, query: str | None = None, *, limit: int = 100):
        self.queries.append(query)
        needle = (query or "").lower()
        rows = [
            studio
            for studio in self.studios
            if not needle
            or needle in studio.name.lower()
            or needle in studio.slug.lower()
            or (studio.owner_email or "").lower().find(needle) >= 0
        ]
        return rows[:limit]

    async def count_studios(self) -> int:
        return len(self.studios)

    async def suspended(self):
        return [
            SuspendedStudio(
                id=studio.id,
                name=studio.name,
                slug=studio.slug,
                plan=studio.plan,
                members=studio.members,
                storage=studio.storage,
                owner_email=studio.owner_email,
                suspension_reason=studio.suspension_reason,
                since=datetime(2026, 11, 20, tzinfo=UTC),
            )
            for studio in self.studios
            if studio.status == "suspended"
        ]

    async def set_status(self, studio_id: uuid.UUID, status: str, reason: str | None = None):
        if studio_id == INTERNAL:
            raise ProtectedStudioError(str(studio_id))
        for index, studio in enumerate(self.studios):
            if studio.id == studio_id:
                updated = studio.model_copy(
                    update={
                        "status": status,
                        "suspension_reason": reason if status == "suspended" else None,
                    }
                )
                self.studios[index] = updated
                self.writes.append((studio_id, status, updated.suspension_reason))
                return updated
        return None

    async def studio_detail(self, studio_id: uuid.UUID, *, days: int = 30, now=None):
        self.days.append(days)
        for studio in self.studios:
            if studio.id == studio_id:
                return StudioDetail(
                    studio=studio,
                    usage_window_days=days,
                    usage=UsageTotals(tokens_in=1200, tokens_out=800, duration_seconds=42.5),
                )
        return None

    async def dashboard(self, *, now=None):
        return Dashboard(
            generated_at=datetime(2026, 11, 21, 10, 42, tzinfo=UTC),
            active_studios=2,
            new_studios_7d=1,
            storage=StorageUsage(used_bytes=412 * 1024**3, quota_bytes=570 * 1024**3, percent=72.3),
            error_rate_5xx_24h=0.2,
            api_latency_p50_ms=120,
            services=[
                ServiceHealth(key="api", label="API", state="ok", detail="Réponse médiane 120 ms"),
                ServiceHealth(
                    key="database",
                    label="Base de données",
                    state="ok",
                    detail="Dernière sauvegarde il y a 5 h",
                ),
            ],
            alerts=[
                Alert(level="warning", title="Stockage à 72,3 % de la capacité", detail="seuil")
            ],
            has_measures=True,
            unpaid_in_grace=None,
        )

    async def usage(self, days: int, *, now=None):
        self.days.append(days)
        rows = [
            StudioUsageRow(
                id=studio.id,
                name=studio.name,
                plan=studio.plan,
                status=studio.status,
                storage=studio.storage,
                members=studio.members,
                members_limit=studio.members_limit,
                usage=UsageTotals(
                    tokens_in=100, tokens_out=50, costs=[CostTotal(currency="EUR", amount="1.25")]
                ),
            )
            for studio in self.studios
        ]
        return UsageReport(
            window_days=days,
            generated_at=datetime(2026, 11, 21, tzinfo=UTC),
            studios=len(self.studios),
            storage=StorageUsage(used_bytes=412 * 1024**3, quota_bytes=570 * 1024**3, percent=72.3),
            api_calls=4_200_000,
            totals=UsageTotals(
                tokens_in=300, tokens_out=150, costs=[CostTotal(currency="EUR", amount="3.75")]
            ),
            top_studios=rows,
            over_quota=[row for row in rows if (row.storage.percent or 0) >= 90],
            has_measures=True,
        )

    async def measures(self, days: int, *, now=None):
        self.days.append(days)
        from studio_contracts.infra import InfraMeasurementsReport, InfraPoint, InfraSeries

        point = InfraPoint(measured_at=datetime(2026, 11, 21, tzinfo=UTC), value=1024)
        return InfraMeasurementsReport(
            window_days=days,
            generated_at=datetime(2026, 11, 21, tzinfo=UTC),
            series=[InfraSeries(metric="storage_bytes", subject="", latest=point, points=[point])],
        )
