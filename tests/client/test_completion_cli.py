from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client import cli


@pytest.mark.parametrize("exit_code", [0, 1])
def test_completion_cli_checks_actual_exit_offline_without_closing_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exit_code: int,
) -> None:
    def unexpected_config():
        raise AssertionError("offline completion check must not load credentials")

    monkeypatch.setattr(cli, "_load_config", unexpected_config)
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "kind": "audit",
                "artifacts": ["vault:report"],
                "checks": [{"name": "artifact check", "status": "passed", "exit_code": exit_code}],
            }
        ),
        encoding="utf-8",
    )
    if exit_code == 0:
        cli.main(["completion", "check", str(path)])
    else:
        with pytest.raises(SystemExit) as error:
            cli.main(["completion", "check", str(path)])
        assert error.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is (exit_code == 0)
    assert result["authoritative"] is False
