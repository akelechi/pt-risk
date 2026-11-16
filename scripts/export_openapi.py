"""Write the API's OpenAPI schema to ui/openapi.json.

UI types are generated from this file (`npm run gen:types` in ui/), never hand-written.
Usage:  python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from api.main import app

TARGET = Path(__file__).resolve().parents[1] / "ui" / "openapi.json"

if __name__ == "__main__":
    TARGET.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {TARGET}")
