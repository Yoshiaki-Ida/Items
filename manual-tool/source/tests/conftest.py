from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import manual_tool.app as app_module
from manual_tool.assembly.project import CompositionProjectStore
from manual_tool.sessions import SessionStore
from manual_tool.workspaces import WorkspaceStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(app_module, "workspace_store", WorkspaceStore())
    monkeypatch.setattr(app_module, "composition_store", CompositionProjectStore())
    with TestClient(app_module.app) as test_client:
        yield test_client
