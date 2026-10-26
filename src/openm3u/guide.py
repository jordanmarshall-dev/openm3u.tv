from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

from .models import Program

ONSCREEN = re.compile(r"S(\d+)\s*E(\d+)", re.I)
TRAILING_YEAR = re.compile(r"\s*\((\d{4})\)\s*$")
TRAILING_EPISODE = re.compile(r"[\s.:,|-]*\bS(\d{1,2})\s*E(\d{1,3})\b[\s.:,|-]*$", re.I)
KIND_LABELS = {"movie": "movie", "series": "episode"}


@dataclass
class Guide:
    names: dict[str, list[str]] = field(default_factory=dict)
    icons: dict[str, str] = field(default_factory=dict)
    programs: dict[str, list[Program]] = field(default_factory=dict)


def read_guide(data: bytes, start: datetime | None = None, stop: datetime | None = None) -> Guide:
    """Read an XMLTV guide. With a window, programmes outside it are skipped while
    parsing, which keeps big guides (Plex lists thousands of channels) small."""
    guide = Guide()
    for _, element in ET.iterparse(io.BytesIO(data), events=("end",)):
        if element.tag == "channel":
            channel_id = element.get("id", "")
            guide.names[channel_id] = [
                n.text.strip() for n in element.findall("display-name") if n.text
            ]
            icon = element.find("icon")
            if icon is not None and icon.get("src"):
                guide.icons[channel_id] = icon.get("src")
            element.clear()
        elif element.tag == "programme":
            program = _program(element)
            if program and start and (program.stop <= start or program.start >= stop):
                program = None
            if program:
                guide.programs.setdefault(element.get("channel", ""), []).append(program)
            element.clear()
    for programs in guide.programs.values():
        programs.sort(key=lambda p: p.start)
    return guide


def _program(element: ET.Element) -> Program | None:
    title = (element.findtext("title") or "").strip()
    if not title:
        return None
    try:
        start = _time(element.get("start", ""))
        stop = _time(element.get("stop", ""))
    except ValueError:
        return None

    kind = None
    categories = []
    for node in element.findall("category"):
        label = (node.text or "").strip()
        if label.lower() in KIND_LABELS:
            kind = KIND_LABELS[label.lower()]
        elif label:
            categories.append(label)

    season = episode = None
    for node in element.findall("episode-num"):
        text = node.text or ""
        if node.get("system") == "onscreen" and (match := ONSCREEN.search(text)):
            season, episode = int(match.group(1)), int(match.group(2))
        elif node.get("system") == "xmltv_ns" and season is None:
            season, episode = _xmltv_ns(text)

    date = element.findtext("date") or ""
    icon = element.find("icon")
    series = element.find("series-id")
    return Program(
        start=start,
        stop=stop,
        title=title,
        subtitle=(element.findtext("sub-title") or "").strip() or None,
        description=(element.findtext("desc") or "").strip() or None,
        season=season,
        episode=episode,
        kind=kind,
        series_id=series.text if series is not None else None,
        categories=categories,
        rating=(element.findtext("rating/value") or "").strip() or None,
        art=icon.get("src") if icon is not None else None,
        year=int(date[:4]) if date[:4].isdigit() else None,
    )


def _time(value: str) -> datetime:
    value = value.strip()
    if " " not in value:
        value += " +0000"
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def _xmltv_ns(text: str) -> tuple[int | None, int | None]:
    parts = [p.split("/")[0].strip() for p in text.split(".")]
    season = int(parts[0]) + 1 if parts and parts[0].isdigit() else None
    episode = int(parts[1]) + 1 if len(parts) > 1 and parts[1].isdigit() else None
    return season, episode


def tidy(program: Program) -> Program:
    """Some feeds glue the episode or year onto the title ("The 100. S01E09",
    "Heat (1995)"). Move them into their own fields so the title is just the name."""
    match = TRAILING_EPISODE.search(program.title)
    if match and match.start() > 0:
        program.title = program.title[: match.start()].strip()
        program.season = program.season or int(match.group(1))
        program.episode = program.episode or int(match.group(2))
        program.kind = program.kind or "episode"
    year = TRAILING_YEAR.search(program.title)
    if year and year.start() > 0 and 1900 < int(year.group(1)) < 2100:
        program.title = program.title[: year.start()].strip()
        program.year = program.year or int(year.group(1))
    return program
