from __future__ import annotations

import os


def env_log_level(name: str, default: str = "summary") -> str:
    value = str(os.getenv(name, default) or default).strip().lower()
    if value in {"0", "false", "no", "off", "quiet"}:
        return "off"
    if value in {"1", "true", "yes", "verbose", "debug", "all"}:
        return "verbose"
    if value in {"summary", "normal", "default", "changes"}:
        return value
    return default


def should_log(name: str, level: str = "summary", default: str = "summary") -> bool:
    current = env_log_level(name, default=default)
    if current == "off":
        return False
    if current == "verbose":
        return True
    if level == "verbose":
        return False
    return True
