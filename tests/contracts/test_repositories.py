from __future__ import annotations

import pytest
from studio_contracts.repositories import normalize_remote_url


def test_scp_like_ssh() -> None:
    assert normalize_remote_url("git@github.com:Owner/Repo.git") == "github.com/owner/repo"


def test_ssh_scheme_with_port() -> None:
    assert normalize_remote_url("ssh://git@github.com:22/Owner/Repo.git") == "github.com/owner/repo"


def test_https_with_git_suffix_and_trailing_slash() -> None:
    assert normalize_remote_url("https://github.com/Owner/Repo.git/") == "github.com/owner/repo"


def test_https_with_credentials_and_port() -> None:
    assert (
        normalize_remote_url("https://user:tok@GitHub.com:443/Owner/Repo")
        == "github.com/owner/repo"
    )


def test_case_is_folded() -> None:
    assert normalize_remote_url("GIT@GITHUB.COM:OWNER/REPO") == "github.com/owner/repo"
    assert normalize_remote_url("https://GitHub.com/Owner/Repo") == "github.com/owner/repo"


def test_git_suffix_is_stripped() -> None:
    assert normalize_remote_url("https://github.com/Owner/Repo.git") == "github.com/owner/repo"


def test_trailing_slash_is_stripped() -> None:
    assert normalize_remote_url("https://github.com/Owner/Repo/") == "github.com/owner/repo"


def test_all_forms_unify() -> None:
    expected = "github.com/owner/repo"
    assert normalize_remote_url("git@github.com:Owner/Repo.git") == expected
    assert normalize_remote_url("ssh://git@github.com:22/Owner/Repo.git") == expected
    assert normalize_remote_url("https://github.com/Owner/Repo.git/") == expected
    assert normalize_remote_url("https://user:tok@GitHub.com:443/Owner/Repo") == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "Owner/Repo",
        "/Owner/Repo",
        "./relative/path",
        "github.com/Owner/Repo",
        "file:///Owner/Repo",
        "file://github.com/Owner/Repo",
        "ftp://github.com/Owner/Repo",
        "https://github.com/Owner",
        "https://github.com/Owner/Repo/extra",
        "https://github.com/",
        "git@github.com:Owner",
        "/home/user/repo",
    ],
)
def test_invalid_urls_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_remote_url(url)
