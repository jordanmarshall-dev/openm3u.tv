from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from .. import __version__
from ..models import Entry, Program

TIME_FORMAT = "%Y%m%d%H%M%S +0000"


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v})
    if text:
        element.text = text
    return element


def _time(value: datetime) -> str:
    return value.strftime(TIME_FORMAT)


def _programme(tv: ET.Element, channel_id: str, program: Program) -> None:
    """Keep the grid clean: the title line is just the show (or the movie and its
    year), and episode numbers and names lead the description instead. No
    episode-num element, because TiviMate tacks it onto the title ("Arrow. S4 E8")."""
    node = _sub(
        tv, "programme", channel=channel_id, start=_time(program.start), stop=_time(program.stop)
    )
    title = program.title
    if program.kind == "movie":
        title = f"{title} ({program.year or '???'})"
    _sub(node, "title", title, lang="en")

    episode = (f"S{program.season:02d}" if program.season else "") + (
        f"E{program.episode:02d}" if program.episode else ""
    )
    lead = " · ".join(filter(None, (episode, program.subtitle)))
    description = "\n".join(filter(None, (lead, program.description)))
    if description:
        _sub(node, "desc", description, lang="en")
    if program.year:
        _sub(node, "date", str(program.year))
    categories = list(program.categories)
    if program.kind == "movie" and "Movie" not in categories:
        categories.append("Movie")
    elif program.kind == "episode" and "Series" not in categories:
        categories.append("Series")
    for category in dict.fromkeys(categories):
        _sub(node, "category", category, lang="en")
    if program.art:
        _sub(node, "icon", src=program.art)
    if program.rating:
        rating = _sub(node, "rating")
        _sub(rating, "value", program.rating)


def render_xmltv(entries: list[Entry], region: str) -> bytes:
    tv = ET.Element("tv", {"generator-info-name": f"openm3u {__version__}"})
    for entry in entries:
        channel = _sub(tv, "channel", id=f"{entry.slug}.{region}")
        _sub(channel, "display-name", entry.channel.name)
        _sub(channel, "display-name", str(entry.number))
        if entry.channel.logo:
            _sub(channel, "icon", src=entry.channel.logo)
    for entry in entries:
        for program in entry.channel.programs:
            _programme(tv, f"{entry.slug}.{region}", program)
    ET.indent(tv, space=" ")
    body = ET.tostring(tv, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n' + body + "\n"
    ).encode()
