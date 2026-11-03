from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import cli


def test_validate_pack_offline_without_loading_server_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_config() -> None:
        raise AssertionError("offline validation must not load machine credentials")

    monkeypatch.setattr(cli, "_load_config", unexpected_config)
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "format": "studio.work-profile-pack/v1",
                "profile": {
                    "stable_key": "example",
                    "title": "Example",
                    "agent_stable_key": "base",
                },
                "base": {
                    "resource_id": str(uuid4()),
                    "kind": "agent_definition",
                    "stable_key": "base",
                    "version": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    cli.main(["library", "profile-preview", str(path), "--validate-only"])
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is True
    assert result["server_checked"] is result["mutates"] is False


@pytest.mark.parametrize(
    "text",
    ['{"format":"unsupported","secret":"do-not-print"}', "x" * 131073],
    ids=["unknown_format", "oversized"],
)
def test_bad_pack_has_a_bounded_explicit_error_without_echoing_content(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        cli.main(["library", "profile-preview", str(path), "--validate-only"])
    assert str(error.value).startswith("invalid_work_profile_pack:")
    assert "do-not-print" not in str(error.value)
