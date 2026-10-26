from __future__ import annotations

from ..fetch import Fetcher
from .base import Source
from .iptvorg import Database, IptvOrg
from .mjh import Fast, FreeToAir
from .playlist import Playlist

TYPES = ("samsung", "pluto", "free-to-air", "iptv-org", "m3u")


def build_source(spec: dict, fetcher: Fetcher, database: Database | None = None) -> Source:
    kind = spec.get("type")
    name = spec.get("name", kind)
    if kind in ("samsung", "pluto"):
        return Fast(name, kind, spec["region"], fetcher, spec.get("base", "https://i.mjh.nz"))
    if kind == "free-to-air":
        return FreeToAir(name, spec["path"], fetcher, spec.get("base", "https://i.mjh.nz"))
    if kind == "iptv-org":
        return IptvOrg(
            name,
            spec["country"],
            spec["files"],
            fetcher,
            database or Database(fetcher),
            include=spec.get("include"),
        )
    if kind == "m3u":
        return Playlist(
            name,
            spec["url"],
            fetcher,
            include=spec.get("include"),
            part_time=spec.get("part_time", False),
            require_guide=spec.get("require_guide", False),
        )
    raise ValueError(f"source {name!r} has unknown type {kind!r}, expected one of {TYPES}")


__all__ = ["Database", "Fast", "FreeToAir", "IptvOrg", "Playlist", "Source", "build_source"]
