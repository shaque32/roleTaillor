"""Keep credentials out of anything written to disk or stdout (logs, eval reports).

`redact` masks two things: the current value of every secret-looking environment
variable, and anything shaped like a provider key even if it came from elsewhere.
"""

from __future__ import annotations

import os
import re

MASK = "[REDACTED]"
_SECRET_ENV_NAME = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|ACCESS_KEY)", re.IGNORECASE)
_MIN_VALUE_LENGTH = 8  # shorter values are placeholders, and masking them would mangle output
_KEY_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}"  # Anthropic
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"  # Stripe secret and restricted keys
    r"|whsec_[A-Za-z0-9]{8,}"  # Stripe webhook signing secret
    r"|sk-[A-Za-z0-9]{24,}"  # DeepSeek / OpenAI-style
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|(?:tid|tsec)_[A-Za-z0-9_-]{16,}"  # Tigris
)
_DB_URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+]*://[^:/@\s]+:)[^@/\s]+(@)")


def _secret_env_values() -> list[str]:
    values = {
        value
        for name, value in os.environ.items()
        if _SECRET_ENV_NAME.search(name) and len(value) >= _MIN_VALUE_LENGTH
    }
    return sorted(values, key=len, reverse=True)  # longest first, so substrings do not survive


def redact(text: str) -> str:
    """Return `text` with credentials replaced by a fixed mask."""
    for value in _secret_env_values():
        if value in text:
            text = text.replace(value, MASK)
    text = _KEY_SHAPES.sub(MASK, text)
    return _DB_URL_PASSWORD.sub(rf"\g<1>{MASK}\g<2>", text)
