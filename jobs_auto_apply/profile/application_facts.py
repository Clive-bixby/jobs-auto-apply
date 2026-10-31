"""Profile facts: YAML helpers over profile/application_facts.yaml."""

from __future__ import annotations

from typing import Any

import yaml

from ..config import AppConfig


def load_application_facts(config: AppConfig) -> dict[str, Any]:
    """Load profile/application_facts.yaml (path from config.paths.application_facts).

    Returns an empty dict when the file is missing or unreadable so that question
    answering degrades to "unknown" instead of crashing a run.
    """
    path = config.base_dir / config.paths.application_facts
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}
