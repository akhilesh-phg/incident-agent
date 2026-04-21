from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEBUG_LOG_PATH = Path(__file__).resolve().parents[1] / "debug-40831c.log"
SESSION_ID = "40831c"


def debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    payload = {
        "sessionId": SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    }
    try:
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        # Debug logging must never break the app flow.
        return

