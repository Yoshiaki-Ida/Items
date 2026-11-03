import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_tools.ticket_creation import redmine_meeting_importer


@pytest.fixture(autouse=True)
def isolate_windows_user_environment(monkeypatch):
    """Keep tests independent from the developer's real Windows user environment."""
    monkeypatch.setattr(
        redmine_meeting_importer,
        "_get_windows_user_environment_variable",
        lambda name: os.environ.get(name, "").strip(),
    )
