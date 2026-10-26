from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections import Counter
from pathlib import Path

import httpx

from . import __version__
from .checks import Checks
from .fetch import Fetcher
from .health import check, probe
from .models import Channel
from .pipeline import run, summary, write
from .regions import load_region
from .settings import Settings, load_settings
from .site import PUBLIC_SITE
from .site import publish as publish_site
from .sources import Database, build_source
from .sources.playlist import parse_m3u, to_channel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openm3u", description="Free, publicly available live TV, organized like basic cable."
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("openm3u.toml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="write a playlist and guide for one region")
    build.add_argument("--region")
    build.add_argument("--skip-health", action="store_true", help="don't test streams")
    build.add_argument("--skip-tmdb", action="store_true", help="don't fetch artwork")

    publish = commands.add_parser("publish", help="build a region into the public site folder")
    publish.add_argument("--region")
    publish.add_argument("--site", type=Path, default=Path("site"))
    publish.add_argument("--skip-health", action="store_true")
    publish.add_argument("--skip-tmdb", action="store_true")

    verify = commands.add_parser(
        "verify", help="test a region's streams from where you are and save the results"
    )
    verify.add_argument("region")
    verify.add_argument("--playlist", help="playlist URL or file (default: the published one)")
    verify.add_argument("--checked-from", help="country you're in (default: the region)")
    verify.add_argument("--out", type=Path, help="where to save (default: checks/<region>.json)")

    categories = commands.add_parser(
        "categories", help="list source labels the shared taxonomy doesn't know yet"
    )
    categories.add_argument("--region")

    single = commands.add_parser("probe", help="test a single stream URL")
    single.add_argument("url")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "probe":
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            report = probe(client, args.url)
        print(report.label, f"{report.bandwidth // 1000} kbps" if report.bandwidth else "")
        return 0 if report.ok else 1

    settings = load_settings(args.config)
    if getattr(args, "region", None):
        settings.region = args.region

    try:
        if args.command == "verify":
            return run_verify(settings, args)
        if args.command == "categories":
            return run_categories(settings)
        if args.command == "publish":
            if not settings.public_url:
                parser.error("publish needs public_url (or domain) set in the config file")
            restore_state(settings)
            result = run(settings, check_health=not args.skip_health, use_tmdb=not args.skip_tmdb)
            files = publish_site(result, args.site, settings.public_url, settings.domain)
            keep_state(settings, args.site, result.region.code)
        else:
            result = run(settings, check_health=not args.skip_health, use_tmdb=not args.skip_tmdb)
            guide_url = (
                f"{settings.public_url}/{result.region.code}.xml.gz" if settings.public_url else ""
            )
            files = write(result, settings.output_dir, guide_url)
    except httpx.HTTPError as exc:
        try:
            where = exc.request.url.host
        except RuntimeError:
            where = "a source"
        print(f"error: couldn't reach {where}: {exc}", file=sys.stderr)
        return 3

    print(summary(result))
    print()
    for file in files:
        print(f"wrote {file}")
    return 0


def run_verify(settings: Settings, args) -> int:
    """Probe every stream in a region's playlist from this machine. Run it from
    inside the country, commit the file it writes, and the next public build
    trusts it for streams it can't test from the US."""
    code = args.region
    location = args.playlist or f"{settings.public_url or PUBLIC_SITE}/{code}.m3u"
    fetcher = Fetcher(mirrors=settings.mirrors)
    used: set[str] = set()
    channels: list[Channel] = [
        to_channel("playlist", e, used) for e in parse_m3u(fetcher.text(location))
    ]
    if not channels:
        print(f"error: no channels in {location}", file=sys.stderr)
        return 1
    print(f"testing {len(channels)} streams from {location}")
    with httpx.Client(timeout=settings.health_timeout, follow_redirects=True) as client:
        check(channels, client, settings.health_concurrency)

    out = args.out or settings.checks_dir / f"{code}.json"
    checks = Checks.load(out) or Checks(code, args.checked_from or code, {})
    checks.checked_from = args.checked_from or checks.checked_from
    checks.record(channels)
    checks.save(out)

    failed = [c for c in channels if not c.report.ok]
    for channel in failed:
        print(f"  {channel.report.label:<16} {channel.name}")
    print(f"{len(channels) - len(failed)} played, {len(failed)} failed. Saved {out}")
    return 0


def run_categories(settings: Settings) -> int:
    """Labels sources use that map to nothing, with how many channels carry each.
    The fix is a line in taxonomy.toml, or a region's [labels] table."""
    region = load_region(settings.region)
    fetcher = Fetcher(mirrors=settings.mirrors)
    database = Database(fetcher)
    unknown: Counter[tuple[str, str]] = Counter()
    for spec in region.sources:
        source = build_source(spec, fetcher, database)
        try:
            channels = source.channels()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            print(f"skipping {source.name}: {exc}", file=sys.stderr)
            continue
        for channel in channels:
            group, skip = region.taxonomy.classify(channel.labels, channel.source)
            if group is None and skip is None:
                for label in channel.labels or ["(none)"]:
                    unknown[(source.name, label)] += 1
    for (source, label), count in unknown.most_common():
        print(f"{count:>5}  {source:<12} {label}")
    if not unknown:
        print(f"every label in {region.name} maps to a group")
    return 0


def restore_state(settings: Settings) -> None:
    """Channel numbers live in the state file. On a fresh machine (like a CI runner),
    pull the copy published with the site so numbers don't reshuffle."""
    code = settings.region
    local = settings.state_dir / f"{code}.json"
    if local.exists():
        return
    for base in filter(None, (settings.public_url, settings.previous_url)):
        try:
            data = httpx.get(f"{base}/state/{code}.json", timeout=20, follow_redirects=True)
            data.raise_for_status()
        except httpx.HTTPError:
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data.content)
        return


def keep_state(settings: Settings, site: Path, code: str) -> None:
    target = site / "state" / f"{code}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(settings.state_dir / f"{code}.json", target)


if __name__ == "__main__":
    sys.exit(main())
