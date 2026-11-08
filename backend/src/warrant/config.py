"""Tiny .env loader (no dependency). Real environment variables win over the file."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> None:
    candidates = [Path(path)] if path else [Path(".env"), Path("../.env"), Path(__file__).resolve().parents[3] / ".env"]
    for p in candidates:
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return
