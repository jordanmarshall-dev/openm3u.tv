from __future__ import annotations

import gzip
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from . import checks, health
from .dedupe import Duplicate, dedupe
from .fetch import Fetcher
from .filters import apply_filters
from .guide import tidy
from .guides import borrow, match_guides
from .language import detect
from .lineup import assign_groups, assign_numbers
from .logos import LogoLibrary, improve
from .models import Channel, Entry, Program, StreamReport
from .output import render_m3u, render_xmltv
from .regions import Region, load_region
from .settings import Settings
from .sources import Database, Source, build_source
from .state import State
from .text import slugify
from .tmdb import Tmdb, enrich

log = logging.getLogger(__name__)

# From outside a region, a 401/403/451 most likely means "not from here", not "dead".
GEO_BLOCKED = re.compile(r"\bhttp (401|403|451)\b")
# Silences shorter than this are left alone; apps draw them as part of the next show.
GAP = timedelta(minutes=15)
HOUR = timedelta(hours=1)


@dataclass
class Build:
    region: Region
    entries: list[Entry] = field(default_factory=list)
    removed: dict[str, list[Channel]] = field(default_factory=dict)
    duplicates: list[Duplicate] = field(default_factory=list)
    pulled: dict[str, int] = field(default_factory=dict)
    ingested: int = 0
    guides_matched: int = 0
    guides_extended: int = 0
    topped_up: int = 0
    loops: int = 0
    confirmed: int = 0
    enriched: int = 0
    placeholders: int = 0
    unlisted: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    guides_failed: list[str] = field(default_factory=list)

    def drop(self, why: str, channels: list[Channel]) -> None:
        if channels:
            self.removed.setdefault(why, []).extend(channels)

    def group_name(self, entry: Entry) -> str:
        return self.region.group(entry.group).name


def run(
    settings: Settings,
    region: Region | None = None,
    sources: dict[str, Source] | None = None,
    check_health: bool = True,
    use_tmdb: bool = True,
    client: httpx.Client | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> Build:
    region = region or load_region(settings.region)
    fetcher = fetcher or Fetcher(mirrors=settings.mirrors)
    if sources is None:
        database = Database(fetcher)
        sources = {
            spec.get("name", spec["type"]): build_source(spec, fetcher, database)
            for spec in region.sources
        }
    start = now or datetime.now(UTC)
    stop = start + timedelta(hours=settings.guide_hours)
    state = State.load(settings.state_dir / f"{region.code}.json")
    state.relayout(region.layout)
    build = Build(region)

    channels = ingest(build, sources, region, fetcher, start, stop)
    groups = classify(build, channels, region)
    channels = [c for c in channels if c.key in groups]
    channels = curate(build, channels, groups, region, settings)
    if check_health:
        channels = test_streams(build, channels, region, settings, state, client, start)

    channels, build.duplicates = dedupe(
        channels, {**region.aliases, **settings.aliases}, settings.source_priority or list(sources)
    )
    if region.logos:
        improve(
            channels,
            LogoLibrary(fetcher, region.logos),
            {d.kept.key: d.dropped for d in build.duplicates},
        )
    entries = assign_groups(channels, region, groups, settings.groups)
    build.loops = sum(1 for e in entries if e.group == region.taxonomy.series)
    build.entries = assign_numbers(entries, region, state, settings.numbers, list(sources))

    if use_tmdb and settings.tmdb_key:
        tmdb = Tmdb(settings.tmdb_key, settings.cache_dir / "tmdb.json")
        programs = [
            p for e in build.entries if not region.group(e.group).live for p in e.channel.programs
        ]
        build.enriched = enrich(programs, tmdb, settings.tmdb_art)

    for entry in build.entries:
        had = bool(entry.channel.programs)
        added = fill(entry.channel, start, stop)
        if not had:
            build.placeholders += 1
            build.unlisted.append(entry.channel.name)
        elif added:
            build.topped_up += 1

    state.save()
    return build


def ingest(
    build: Build,
    sources: dict[str, Source],
    region: Region,
    fetcher: Fetcher,
    start: datetime,
    stop: datetime,
) -> list[Channel]:
    """Every source's channels and listings, with the region's guides filling gaps."""
    channels: list[Channel] = []
    for name, source in sources.items():
        try:
            found = source.channels()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            log.warning("%s is unavailable, building without it: %s", name, exc)
            build.unavailable.append(name)
            continue
        try:
            source.schedule(found, start, stop)
        except (httpx.HTTPError, OSError, ET.ParseError) as exc:
            log.warning("%s: no guide (%s)", name, exc)
        for why, dropped in source.removed.items():
            build.drop(why, dropped)
        build.pulled[name] = len(found) + sum(len(v) for v in source.removed.values())
        channels.extend(found)
    build.ingested = sum(build.pulled.values())

    build.guides_matched, build.guides_extended = match_guides(
        channels, region.guides, fetcher, start, stop, region.guide_names, build.guides_failed
    )
    borrow(channels, region.guide_fallback)
    for channel in channels:
        channel.programs = [tidy(p) for p in channel.programs]

    strict = {name for name, source in sources.items() if source.require_guide}
    unlisted = [c for c in channels if c.source in strict and not c.curated and not c.programs]
    build.drop("no guide", unlisted)
    dropped = {id(c) for c in unlisted}
    return [c for c in channels if id(c) not in dropped]


def classify(build: Build, channels: list[Channel], region: Region) -> dict[str, str]:
    """Each channel's group, from its labels, then its guide, then its name.
    Channels whose labels say shopping, religion or adult are left out here."""
    taxonomy = region.taxonomy
    groups: dict[str, str] = {}
    for channel in channels:
        group, skip = taxonomy.classify(channel.labels, channel.source)
        if group is None and skip is None:
            group, skip = taxonomy.guess(channel)
        if skip:
            build.drop(skip, [channel])
            continue
        groups[channel.key] = group or taxonomy.fallback
        channel.language = channel.language or taxonomy.language(channel.labels)
    return groups


def curate(
    build: Build,
    channels: list[Channel],
    groups: dict[str, str],
    region: Region,
    settings: Settings,
) -> list[Channel]:
    """Hide lists, one-show loops and other languages."""

    def live(channel: Channel) -> bool:
        return region.group(groups[channel.key]).live

    channels, hidden, loops = apply_filters(
        channels, [*region.hide, *settings.hide], settings.keep, exempt=live
    )
    build.drop("hidden", hidden)
    if settings.single_show == "hide":
        build.drop("one-show loops", loops)
        dropped = {id(c) for c in loops}
        channels = [c for c in channels if id(c) not in dropped]
    elif settings.single_show == "group" and region.taxonomy.has(region.taxonomy.series):
        for channel in loops:
            groups[channel.key] = region.taxonomy.series

    if settings.other_languages == "off":
        return channels
    foreign = []
    for channel in channels:
        channel.language = detect(channel, region.language)
        if channel.language == region.language:
            continue
        block = region.language_group(channel.language)
        if settings.other_languages == "group" and block:
            groups[channel.key] = block
        else:
            foreign.append(channel)
    build.drop("other language", foreign)
    return [c for c in channels if c not in foreign]


def test_streams(
    build: Build,
    channels: list[Channel],
    region: Region,
    settings: Settings,
    state: State,
    client: httpx.Client | None,
    now: datetime,
) -> list[Channel]:
    """Open every stream. Away from home, a refusal is inconclusive, and a check
    run from inside the country (see checks.py) settles it."""
    client = client or httpx.Client(timeout=settings.health_timeout, follow_redirects=True)
    health.check(channels, client, settings.health_concurrency)
    if settings.runs_in and settings.runs_in != region.code:
        for channel in channels:
            if GEO_BLOCKED.search(channel.report.reason or ""):
                channel.report = StreamReport(True, "unverified")
        found = checks.Checks.load(settings.checks_dir / f"{region.code}.json")
        if found:
            confirmed, failed = checks.apply(channels, found, settings.check_days, now.timestamp())
            build.confirmed = len(confirmed)
            build.drop(f"failed in {found.checked_from.upper()}", failed)

    for channel in channels:
        state.record_health(slugify(channel.name), channel.report.ok, channel.report.label)
    settled = {id(c) for chs in build.removed.values() for c in chs}
    build.drop("drm", [c for c in channels if c.report.reason == "drm"])
    build.drop(
        "dead",
        [
            c
            for c in channels
            if not c.report.ok and c.report.reason != "drm" and id(c) not in settled
        ],
    )
    channels = [c for c in channels if c.report.ok]
    floor = settings.min_height
    build.drop(f"below {floor}p", [c for c in channels if 0 < c.report.height < floor])
    return [c for c in channels if not 0 < c.report.height < floor]


def fill(channel: Channel, start: datetime, stop: datetime) -> int:
    """Cover the whole guide window so no slot ever reads "No information".

    Wherever the listings are silent (no guide at all, a gap, or a guide that
    runs out before the window does) hour blocks named after the channel fill
    in. Returns how many blocks were added."""
    programs = sorted(channel.programs, key=lambda p: p.start)
    edge = start.replace(minute=0, second=0, microsecond=0)
    blocks: list[Program] = []
    for program in [*programs, None]:
        until = program.start if program else stop
        while until - edge >= GAP:
            end = min(until, edge.replace(minute=0, second=0, microsecond=0) + HOUR)
            blocks.append(_block(channel, edge, end))
            edge = end
        if program:
            edge = max(edge, program.stop)
    channel.programs = sorted([*programs, *blocks], key=lambda p: p.start)
    return len(blocks)


def _block(channel: Channel, start: datetime, stop: datetime) -> Program:
    return Program(
        start,
        stop,
        channel.name,
        description=channel.description or f"Live programming on {channel.name}.",
    )


def write(build: Build, out_dir: Path, guide_url: str = "") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    code = build.region.code
    playlist = out_dir / f"{code}.m3u"
    guide = out_dir / f"{code}.xml.gz"
    playlist.write_text(render_m3u(build.entries, code, build.group_name, guide_url))
    guide.write_bytes(gzip.compress(render_xmltv(build.entries, code), mtime=0))
    return [playlist, guide]


def summary(build: Build) -> str:
    lines = [
        f"{build.region.name}: {build.ingested} channels in, {len(build.entries)} in the lineup"
    ]
    lines += [f"  pulled  {n:>4}  {name}" for name, n in build.pulled.items()]
    lines += [f"  missing       {name} (unavailable this run)" for name in build.unavailable]
    lines += [f"  missing       guide {url}" for url in build.guides_failed]
    if build.guides_matched:
        lines.append(f"  listed  {build.guides_matched:>4}  from the region's guides")
    lines += [f"  removed {len(chs):>4}  {why}" for why, chs in build.removed.items() if chs]
    if build.loops:
        lines.append(f"  moved   {build.loops:>4}  one-show loops into their own group")
    merged = sum(len(d.dropped) for d in build.duplicates)
    if merged:
        lines.append(f"  merged  {merged:>4}  duplicates")
    if build.confirmed:
        lines.append(f"  checked {build.confirmed:>4}  streams confirmed from inside the country")

    heights = [e.channel.report.height for e in build.entries if e.channel.report]
    if any(heights):
        full = sum(h >= 1080 for h in heights)
        hd = sum(720 <= h < 1080 for h in heights)
        lines.append(f"  {full} in 1080p, {hd} in 720p, {len(heights) - full - hd} unmeasured")
    if build.enriched:
        lines.append(f"  {build.enriched} guide entries enriched from TMDB")
    if build.guides_extended:
        lines.append(f"  {build.guides_extended} short guides continued from another guide")
    if build.topped_up:
        lines.append(f"  {build.topped_up} channels had gaps filled with named blocks")
    if build.placeholders:
        lines.append(f"  {build.placeholders} channels have no published guide yet")

    lines.append("")
    blocks: dict[str, list[int]] = {}
    for entry in build.entries:
        blocks.setdefault(build.group_name(entry), []).append(entry.number)
    for group, numbers in blocks.items():
        lines.append(f"  {min(numbers):>4}  {group} ({len(numbers)})")
    return "\n".join(lines)
