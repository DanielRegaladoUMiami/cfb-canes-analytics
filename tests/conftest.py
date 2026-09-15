from __future__ import annotations

import pytest

from cfb_canes_analytics import _http


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep backoff logic exercised but instantaneous."""
    monkeypatch.setattr(_http.time, "sleep", lambda _seconds: None)
