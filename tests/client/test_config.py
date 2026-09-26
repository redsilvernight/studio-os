from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_client.config import ClientConfig, client_channel, default_config_path


def test_requires_api_base_url() -> None:
    with pytest.raises(ValidationError):
        ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML


def test_strips_trailing_slash() -> None:
    config = ClientConfig(api_base_url="https://vps.example.com/")
    assert config.api_base_url == "https://vps.example.com"


def test_env_used_when_init_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")
    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML
    assert config.api_base_url == "https://from-env.example.com"


def test_init_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")
    config = ClientConfig(api_base_url="https://from-init.example.com")
    assert config.api_base_url == "https://from-init.example.com"


def test_toml_file_used_when_env_and_init_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('api_base_url = "https://from-toml.example.com"\n')
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert config.api_base_url == "https://from-toml.example.com"


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('api_base_url = "https://from-toml.example.com"\n')
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert config.api_base_url == "https://from-env.example.com"


def test_missing_toml_file_is_silently_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(tmp_path / "does-not-exist.toml"))
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert config.api_base_url == "https://from-env.example.com"


def test_default_config_path_is_platform_specific() -> None:
    assert default_config_path().name == "config.toml"


def test_dev_channel_keeps_its_own_data_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_CLIENT_CHANNEL", raising=False)
    assert client_channel() == "prod"
    stable = default_config_path().parent
    monkeypatch.setenv("STUDIO_CLIENT_CHANNEL", "dev")
    assert client_channel() == "dev"
    dev = default_config_path().parent
    assert dev != stable
    assert dev.parent == stable.parent
    assert dev.name.lower() == f"{stable.name.lower()}-dev"


def test_unknown_channel_is_the_stable_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_CHANNEL", "staging")
    assert client_channel() == "prod"


def test_defaults_cover_idempotency_reclaim_window() -> None:
    """The default read timeout must not be shorter than the server's
    `_PENDING_RECLAIM_SECONDS` (30s, `services/api/src/studio_api/services/
    idempotency.py`) — otherwise a client would time out while a legitimate
    idempotent creation is still being processed by another request."""
    config = ClientConfig(api_base_url="https://vps.example.com")
    assert config.read_timeout >= 30.0


# --- Git watches (multi-repo, DEC-0032 addendum) ---------------------------

BASE_URL = "https://vps.example.com"


def _watch(path: Path, project_id: object) -> dict[str, object]:
    return {"repo_path": str(path), "project_id": str(project_id)}


def test_no_git_config_yields_no_git_watches() -> None:
    assert ClientConfig(api_base_url=BASE_URL).git_watches == ()


def test_git_watches_single_and_multiple(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    watches = [_watch(tmp_path / name, pid) for name, pid in zip("abc", ids, strict=True)]

    one = ClientConfig(api_base_url=BASE_URL, git_watches=watches[:1])
    three = ClientConfig(api_base_url=BASE_URL, git_watches=watches)

    assert [w.project_id for w in one.git_watches] == ids[:1]
    assert [w.project_id for w in three.git_watches] == ids
    assert [w.repo_path for w in three.git_watches] == [tmp_path / n for n in "abc"]


def test_legacy_pair_is_normalised_into_one_git_watch(tmp_path: Path) -> None:
    project_id = uuid4()

    config = ClientConfig(
        api_base_url=BASE_URL, git_watch_repo_path=tmp_path, git_watch_project_id=project_id
    )

    assert [(w.repo_path, w.project_id) for w in config.git_watches] == [(tmp_path, project_id)]
    assert config.git_watch_repo_path is None
    assert config.git_watch_project_id is None


def test_legacy_pair_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", BASE_URL)
    monkeypatch.setenv("STUDIO_CLIENT_GIT_WATCH_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("STUDIO_CLIENT_GIT_WATCH_PROJECT_ID", str(project_id))

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert [(w.repo_path, w.project_id) for w in config.git_watches] == [(tmp_path, project_id)]


def test_git_watches_from_toml_array_of_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    id_a, id_b = uuid4(), uuid4()
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        chr(10).join(
            [
                f'api_base_url = "{BASE_URL}"',
                "[[git_watches]]",
                f"repo_path = '{tmp_path / 'a'}'",
                f"project_id = '{id_a}'",
                "[[git_watches]]",
                f"repo_path = '{tmp_path / 'b'}'",
                f"project_id = '{id_b}'",
            ]
        )
    )
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert [w.project_id for w in config.git_watches] == [id_a, id_b]


def test_legacy_toml_keys_still_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        chr(10).join(
            [
                f'api_base_url = "{BASE_URL}"',
                f"git_watch_repo_path = '{tmp_path}'",
                f"git_watch_project_id = '{project_id}'",
            ]
        )
    )
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))

    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    assert [(w.repo_path, w.project_id) for w in config.git_watches] == [(tmp_path, project_id)]


def test_git_watch_without_project_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ClientConfig(api_base_url=BASE_URL, git_watches=[{"repo_path": str(tmp_path)}])


def test_git_watch_without_repo_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientConfig(api_base_url=BASE_URL, git_watches=[{"project_id": str(uuid4())}])


def test_legacy_half_pair_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        ClientConfig(api_base_url=BASE_URL, git_watch_repo_path=tmp_path)
    with pytest.raises(ValidationError, match="must be set together"):
        ClientConfig(api_base_url=BASE_URL, git_watch_project_id=uuid4())


def test_duplicate_repo_is_rejected_even_for_other_project(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="twice"):
        ClientConfig(
            api_base_url=BASE_URL,
            git_watches=[_watch(tmp_path / "a", uuid4()), _watch(tmp_path / "a", uuid4())],
        )


def test_duplicate_repo_detected_across_path_spellings(tmp_path: Path) -> None:
    project_id = uuid4()
    with pytest.raises(ValidationError, match="twice"):
        ClientConfig(
            api_base_url=BASE_URL,
            git_watches=[
                _watch(tmp_path / "a", project_id),
                _watch(tmp_path / "x" / ".." / "a", project_id),
            ],
        )
    if os.name == "nt":
        with pytest.raises(ValidationError, match="twice"):
            ClientConfig(
                api_base_url=BASE_URL,
                git_watches=[
                    _watch(str(tmp_path / "a").upper(), project_id),
                    _watch(str(tmp_path / "a").lower().replace("\\", "/"), project_id),
                ],
            )


def test_relative_repo_path_is_made_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config = ClientConfig(
        api_base_url=BASE_URL,
        git_watches=[_watch(Path("repo"), uuid4())],  # type: ignore[arg-type]
    )

    assert config.git_watches[0].repo_path == tmp_path / "repo"


def test_same_project_may_watch_several_repos(tmp_path: Path) -> None:
    project_id = uuid4()

    config = ClientConfig(
        api_base_url=BASE_URL,
        git_watches=[_watch(tmp_path / "front", project_id), _watch(tmp_path / "back", project_id)],
    )

    assert len(config.git_watches) == 2
    assert config.git_repo_for_project(project_id) == tmp_path / "front"
    assert config.git_repo_for_project(uuid4()) is None


def test_legacy_and_new_formats_together_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="both set"):
        ClientConfig(
            api_base_url=BASE_URL,
            git_watches=[_watch(tmp_path / "a", uuid4())],
            git_watch_repo_path=tmp_path / "b",
            git_watch_project_id=uuid4(),
        )
