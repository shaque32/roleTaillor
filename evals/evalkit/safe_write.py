"""Every eval file goes to disk through here, so a credential that slipped into model
output or an error message is masked first. Uses the application's redaction filter
(roletailor.redaction, added with the secret-scanning work); until that module is on
this branch, a local filter covering the same key shapes stands in."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    from roletailor.redaction import redact
except ImportError:  # the shared filter has not been merged into this branch yet
    _KEYS = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"
                       r"|whsec_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16}")
    _SECRET_NAME = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|ACCESS_KEY)", re.IGNORECASE)

    def redact(text: str) -> str:
        values = {v for k, v in os.environ.items() if _SECRET_NAME.search(k) and len(v) >= 8}
        for value in sorted(values, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return _KEYS.sub("[REDACTED]", text)


def write_text(path: Path, text: str) -> None:
    path.write_text(redact(text))


def write_json(path: Path, data, **kw) -> None:
    kw.setdefault("indent", 2)
    write_text(path, json.dumps(data, **kw) + "\n")
