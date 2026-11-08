from __future__ import annotations

import asyncio
from types import SimpleNamespace

from studio_client.context.library import LibraryContextProvider


class _Api:
    def __init__(self, total: int) -> None:
        self.rows = [SimpleNamespace(id=i) for i in range(total)]
        self.calls = 0

    async def list_library_resources(self, *, limit: int, offset: int = 0, **_: object):
        self.calls += 1
        return self.rows[offset : offset + limit]


def test_list_all_pages_without_silent_truncation() -> None:
    api = _Api(250)
    got = asyncio.run(LibraryContextProvider(api)._list_all(limit=100))
    assert len(got) == 250
    assert api.calls == 3


def test_list_all_exact_multiple_ends_on_empty_page() -> None:
    api = _Api(200)
    assert len(asyncio.run(LibraryContextProvider(api)._list_all(limit=100))) == 200
