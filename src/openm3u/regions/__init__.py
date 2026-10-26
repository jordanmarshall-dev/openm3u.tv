from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from importlib import resources
from pathlib import Path

from ..taxonomy import Group, Taxonomy, load_taxonomy
from ..text import fold

CODES = ("ca", "us", "uk", "au", "nz")
LANGUAGE_BLOCK = 100


@dataclass
class Region:
    code: str
    name: str
    taxonomy: Taxonomy
    sources: list[dict]
    language: str = "en"
    layout: int = 1
    min_group_size: int = 3
    guides: list[str] = field(default_factory=list)
    guide_names: dict[str, str] = field(default_factory=dict)
    guide_fallback: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    featured: list[str] = field(default_factory=list)
    places: dict[str, list[str]] = field(default_factory=dict)
    logos: list[str] = field(default_factory=list)
    hide: list[str] = field(default_factory=list)

    @property
    def groups(self) -> list[Group]:
        return self.taxonomy.groups

    def group(self, group_id: str) -> Group:
        return self.taxonomy.group(group_id)

    def language_group(self, language: str) -> str | None:
        return next((g.id for g in self.groups if g.language == language), None)

    def prominence(self, name: str) -> int:
        """Where a channel ranks within its group: the first featured pattern it
        matches, so CBC and CTV sit above the niche channels."""
        lowered = name.lower()
        for i, pattern in enumerate(self.featured):
            if fnmatchcase(lowered, pattern.lower()):
                return i
        return len(self.featured)

    def place(self, text: str) -> int:
        """Index of the place a channel serves, in the region's order (west to east
        for Canada). Channels that aren't tied to a place come first."""
        words = f" {fold(text)} "
        for i, keywords in enumerate(self.places.values()):
            if any(f" {fold(k)} " in words for k in keywords):
                return i + 1
        return 0


def load_region(code: str, path: Path | None = None) -> Region:
    if path is None:
        text = resources.files("openm3u.regions").joinpath(f"{code}.toml").read_text()
    else:
        text = path.read_text()
    raw = tomllib.loads(text)

    extra = []
    for i, item in enumerate(raw.get("languages", [])):
        start = item.get("start", 1400 + i * LANGUAGE_BLOCK)
        extra.append(
            Group(
                id=f"lang-{item['code']}",
                name=item["name"],
                start=start,
                size=item.get("size", LANGUAGE_BLOCK),
                sort=item.get("sort", "place"),
                keep_small=True,
                language=item["code"],
            )
        )
    taxonomy = load_taxonomy().adjusted(raw.get("groups"), raw.get("labels"), extra)

    return Region(
        code=raw["code"],
        name=raw["name"],
        taxonomy=taxonomy,
        sources=raw["sources"],
        language=raw.get("language", "en"),
        layout=raw.get("layout", 1),
        min_group_size=raw.get("min_group_size", 3),
        guides=raw.get("guides", []),
        guide_names=raw.get("guide_names", {}),
        guide_fallback=raw.get("guide_fallback", {}),
        aliases=raw.get("aliases", {}),
        featured=raw.get("featured", []),
        places=raw.get("places", {}),
        logos=raw.get("logos", []),
        hide=raw.get("hide", []),
    )
