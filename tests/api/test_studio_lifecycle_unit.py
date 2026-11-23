"""Pure-unit checks of the studio lifecycle helpers (0051).

No database and no object storage: the archive layout, the JSON encoder and
the catalog-driven delete planner are exercised in isolation so a regression is
caught even when PostgreSQL/MinIO are absent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from studio_api.db.models.studio import StudioModel
from studio_api.services import studio_deletion as deletion
from studio_api.services import studio_export as export
from studio_api.settings import get_settings


def test_export_object_key_is_scoped_and_dated() -> None:
    studio = StudioModel(slug="alpha", name="Alpha")
    studio.id = uuid.uuid4()
    export_id = uuid.uuid4()
    now = datetime(2026, 11, 22, 10, 30, tzinfo=UTC)

    key = export.export_object_key(studio, export_id, now)

    assert key == f"studios/{studio.id}/exports/{export_id}/studio-alpha-20261122T103000Z.zip"


def test_json_value_encodes_python_only_types() -> None:
    identifier = uuid.uuid4()
    moment = datetime(2026, 11, 22, 10, 30, tzinfo=UTC)

    assert export._json_value(identifier) == str(identifier)
    assert export._json_value(moment) == "2026-11-22T10:30:00+00:00"
    assert export._json_value({"a": [identifier, moment]}) == {
        "a": [str(identifier), "2026-11-22T10:30:00+00:00"]
    }
    assert export._json_value(b"\x01\xff") == "01ff"
    assert export._json_value(None) is None


def test_predicates_cover_a_project_scoped_child_table() -> None:
    """A table with no `studio_id` and no studio-scoped child (roadmaps) must
    still be reached through its `projects` parent."""
    edges = [
        deletion._FkEdge("projects", "studio_id", "studios"),
        deletion._FkEdge("roadmaps", "project_id", "projects"),
        deletion._FkEdge("tasks", "project_id", "projects"),
        deletion._FkEdge("agents", "superseded_by_agent_id", "agents"),
    ]

    templates = deletion._predicate_templates(edges, {"projects"})

    assert templates["projects"] == "{a}.studio_id = :studio_id"
    assert templates["roadmaps"] is not None
    assert '"project_id" IN (SELECT _projects.id FROM "projects" _projects' in templates["roadmaps"]
    # A self-reference is skipped (a single DELETE removes both ends).
    assert templates["agents"] is None


def test_delete_order_puts_children_before_parents() -> None:
    edges = [
        deletion._FkEdge("roadmaps", "project_id", "projects"),
        deletion._FkEdge("tasks", "project_id", "projects"),
        deletion._FkEdge("claims", "task_id", "tasks"),
    ]

    order = deletion._delete_order(edges, {"projects", "roadmaps", "tasks", "claims"})

    assert order.index("claims") < order.index("tasks")
    assert order.index("tasks") < order.index("projects")
    assert order.index("roadmaps") < order.index("projects")


def test_settings_bound_the_export_link_and_announce_the_grace_window() -> None:
    settings = get_settings()

    assert settings.deletion_grace_days == 14
    assert settings.export_url_ttl_seconds <= 15 * 60
    assert settings.export_retention_days >= 1
    assert settings.deletion_backup_retention_days >= settings.deletion_grace_days
