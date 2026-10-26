from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    region: str = "ca"
    output_dir: Path = Path("output")
    state_dir: Path = Path("state")
    cache_dir: Path = Path("cache")
    checks_dir: Path = Path("checks")
    public_url: str = ""
    previous_url: str = ""
    domain: str = ""
    guide_hours: int = 48
    single_show: str = "group"
    other_languages: str = "group"
    min_height: int = 720
    keep: list[str] = field(default_factory=list)
    hide: list[str] = field(default_factory=list)
    groups: dict[str, str] = field(default_factory=dict)
    numbers: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    source_priority: list[str] = field(default_factory=list)
    health_concurrency: int = 6
    health_timeout: float = 10
    check_days: int = 14
    runs_in: str = ""
    tmdb_art: str = "landscape"
    tmdb_key: str = ""
    mirrors: dict[str, str] = field(default_factory=dict)


def load_settings(path: Path | None) -> Settings:
    raw = tomllib.loads(path.read_text()) if path and path.exists() else {}
    filters = raw.get("filters", {})
    health = raw.get("health", {})
    tmdb = raw.get("tmdb", {})
    settings = Settings(
        region=raw.get("region", "ca"),
        output_dir=Path(raw.get("output_dir", "output")),
        state_dir=Path(raw.get("state_dir", "state")),
        cache_dir=Path(raw.get("cache_dir", "cache")),
        checks_dir=Path(raw.get("checks_dir", "checks")),
        public_url=raw.get("public_url", "").rstrip("/"),
        previous_url=raw.get("previous_url", "").rstrip("/"),
        domain=raw.get("domain", "").strip(),
        guide_hours=raw.get("guide_hours", 48),
        single_show=_mode("single_show", filters.get("single_show", "group")),
        other_languages=_mode("other_languages", filters.get("other_languages", "group")),
        min_height=filters.get("min_height", 720),
        keep=filters.get("keep", []),
        hide=filters.get("hide", []),
        groups=raw.get("groups", {}),
        numbers=raw.get("numbers", {}),
        aliases=raw.get("aliases", {}),
        source_priority=raw.get("source_priority", []),
        health_concurrency=health.get("concurrency", 6),
        health_timeout=health.get("timeout", 10),
        check_days=health.get("check_days", 14),
        runs_in=health.get("runs_in", ""),
        tmdb_art=tmdb.get("art", "landscape"),
        mirrors=raw.get("mirrors", {}),
    )
    if settings.domain:
        settings.public_url = f"https://{settings.domain}"
    settings.tmdb_key = os.environ.get("TMDB_API_KEY", tmdb.get("api_key", ""))
    return settings


def _mode(key: str, value) -> str:
    if value is True:
        return "group"
    if value is False:
        return "off"
    if value not in ("group", "hide", "off"):
        raise ValueError(f'filters.{key} must be "group", "hide" or "off", not {value!r}')
    return value
