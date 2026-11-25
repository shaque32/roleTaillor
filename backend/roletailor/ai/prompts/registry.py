"""Versioned prompt registry.

Prompts live next to this file as `<key>.v<N>.md` with YAML front matter. The body is
the static system prompt; `{{> name}}` includes `_partials/name.md`. Bodies contain no
per-request values, so each version is a stable cache prefix. Versions are pinned per
environment in config/models.yaml (`prompt_pins`); rollback is a pin change.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).parent
_FILE_RE = re.compile(r"^(?P<key>[a-z_]+)\.v(?P<version>\d+)\.md$")
_INCLUDE_RE = re.compile(r"\{\{>\s*([a-z_]+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    key: str
    version: int
    description: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _render(body: str, directory: Path) -> str:
    def include(m: re.Match) -> str:
        return (directory / "_partials" / f"{m.group(1)}.md").read_text().strip()

    return _INCLUDE_RE.sub(include, body).strip() + "\n"


def _parse(path: Path, directory: Path) -> Prompt:
    raw = path.read_text()
    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: missing front matter")
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    m = _FILE_RE.match(path.name)
    if not m or meta["key"] != m["key"] or int(meta["version"]) != int(m["version"]):
        raise ValueError(f"{path.name}: front matter does not match file name")
    return Prompt(key=meta["key"], version=int(meta["version"]),
                  description=meta.get("description", ""), text=_render(body, directory))


class PromptRegistry:
    def __init__(self, directory: Path = PROMPT_DIR, pins: dict[str, int] | None = None):
        self._pins = pins or {}
        self._prompts: dict[str, dict[int, Prompt]] = {}
        for path in sorted(directory.glob("*.v*.md")):
            p = _parse(path, directory)
            self._prompts.setdefault(p.key, {})[p.version] = p

    def get(self, key: str, version: int | None = None) -> Prompt:
        versions = self._prompts.get(key)
        if not versions:
            raise KeyError(f"unknown prompt {key!r}")
        v = version or self._pins.get(key) or max(versions)
        return versions[v]

    def keys(self) -> list[str]:
        return sorted(self._prompts)


@lru_cache
def default_registry(pins: tuple[tuple[str, int], ...] = ()) -> PromptRegistry:
    return PromptRegistry(pins=dict(pins))
