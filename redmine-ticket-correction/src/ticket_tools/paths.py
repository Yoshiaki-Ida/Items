import os
from pathlib import Path

APP_ROOT = Path(os.environ.get('TICKET_TOOLS_HOME', Path(__file__).resolve().parents[2])).resolve()