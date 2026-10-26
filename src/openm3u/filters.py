from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase

from .models import Channel
from .text import fold, unbranded

NAMED_SHARE = 0.8
UNNAMED_SHARE = 0.95
UNNAMED_MIN_HOURS = 36


@dataclass
class Dominance:
    title: str
    share: float
    hours: float


def dominance(channel: Channel) -> Dominance | None:
    airtime: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for program in channel.programs:
        key = program.series_id or fold(program.title)
        airtime[key] += program.seconds
        titles.setdefault(key, program.title)
    total = sum(airtime.values())
    if not total:
        return None
    key, seconds = airtime.most_common(1)[0]
    return Dominance(titles[key], seconds / total, total / 3600)


def is_single_show(channel: Channel) -> bool:
    """A channel is a one-show loop if a single series fills most of its airtime.

    When the channel is named after the show (Ink Master, South Park: Kyle Collection)
    a lower share is enough. Otherwise we need a near-total share over a long window,
    so a genre channel that happens to be running a marathon today isn't caught."""
    found = dominance(channel)
    if found is None:
        return False
    name = _squash(unbranded(channel.name))
    show = _squash(found.title)
    named = len(show) >= 3 and len(name) >= 3 and (show in name or name in show)
    if named:
        return max(found.share, _franchise_share(channel, show)) >= NAMED_SHARE
    return found.share >= UNNAMED_SHARE and found.hours >= UNNAMED_MIN_HOURS


def _squash(text: str) -> str:
    return fold(text).replace(" ", "")


def _franchise_share(channel: Channel, show: str) -> float:
    """Specials and spin-offs ("Arthur and the Haunted Tree House") count toward the show."""
    total = sum(p.seconds for p in channel.programs)
    related = sum(p.seconds for p in channel.programs if show in _squash(p.title))
    return related / total if total else 0.0


def matches(channel: Channel, names: list[str]) -> bool:
    """Exact name, a name prefix ("South Park" covers "South Park: Kyle Collection"),
    or the source's own channel id. Patterns with * match names or ids."""
    if channel.source_id in names:
        return True
    name = fold(channel.name)
    for wanted in names:
        if "*" in wanted:
            pattern = wanted.lower()
            if fnmatchcase(channel.name.lower(), pattern) or fnmatchcase(
                channel.source_id.lower(), pattern
            ):
                return True
        elif (w := fold(wanted)) and (name == w or name.startswith(w + " ")):
            return True
    return False


def apply_filters(
    channels: list[Channel],
    hide: list[str],
    keep: list[str],
    exempt: Callable[[Channel], bool] = lambda channel: False,
) -> tuple[list[Channel], list[Channel], list[Channel]]:
    """Split channels into (visible, hidden, one-show loops).

    Loops stay in the visible list; the caller decides whether to shelve them in
    their own group or drop them. Channels on the keep list, or exempt ones like
    newscasts, are never treated as loops."""
    visible, hidden, loops = [], [], []
    for channel in channels:
        if matches(channel, hide):
            hidden.append(channel)
            continue
        visible.append(channel)
        if not exempt(channel) and not matches(channel, keep) and is_single_show(channel):
            loops.append(channel)
    return visible, hidden, loops
