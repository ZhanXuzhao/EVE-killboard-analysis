from __future__ import annotations

import types

import pytest

from src.collector import zkillboard


class DummyResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_post_names_request_falls_back_to_v1(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append((url, json, timeout, headers))
        if url == zkillboard._ESI_NAMES_URLS[0]:
            return DummyResponse(404, text="not found")
        return DummyResponse(200, [{"id": 42, "name": "Test"}])

    monkeypatch.setattr(zkillboard._session, "post", fake_post)

    result = zkillboard._post_names_request([42])

    assert result == [{"id": 42, "name": "Test"}]
    assert calls[0][0] == zkillboard._ESI_NAMES_URLS[0]
    assert calls[1][0] == zkillboard._ESI_NAMES_URLS[1]


def test_post_names_request_returns_empty_on_all_failures(monkeypatch):
    def fake_post(url, json=None, timeout=None, headers=None):
        return DummyResponse(404, text="not found")

    monkeypatch.setattr(zkillboard._session, "post", fake_post)

    result = zkillboard._post_names_request([42])

    assert result == []
