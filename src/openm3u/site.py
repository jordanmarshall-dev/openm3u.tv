from __future__ import annotations

import json
import time
from html import escape
from importlib import resources
from pathlib import Path

from .models import Entry
from .pipeline import Build, write
from .taxonomy import OVERFLOW

REPO = "https://github.com/jordanmarshall-dev/openm3u.tv"
PUBLIC_SITE = "https://jordanmarshall-dev.github.io/openm3u.tv"
ASSETS = ("og.png", "favicon.png", "apple-touch-icon.png")


def publish(build: Build, site: Path, public_url: str, domain: str = "") -> list[Path]:
    """Write one region's files into the site folder and rebuild the index page."""
    site.mkdir(parents=True, exist_ok=True)
    code = build.region.code
    base = public_url.rstrip("/")
    guide_url = f"{base}/{code}.xml.gz" if base else f"{code}.xml.gz"
    playlist, guide = write(build, site, guide_url)

    status = site / f"{code}.json"
    status.write_text(json.dumps(_status(build, base), indent=1))
    index = site / "index.html"
    index.write_text(render_index(_regions(site), base))
    assets = resources.files("openm3u.templates")
    for asset in ASSETS:
        (site / asset).write_bytes(assets.joinpath(asset).read_bytes())
    (site / ".nojekyll").touch()
    if domain:
        (site / "CNAME").write_text(domain + "\n")
    return [playlist, guide, status, index]


def _reason(entry: Entry) -> str | None:
    return entry.channel.report.reason if entry.channel.report else None


def _status(build: Build, base: str) -> dict:
    code = build.region.code
    return {
        "code": code,
        "name": build.region.name,
        "updated": int(time.time()),
        "playlist": f"{base}/{code}.m3u",
        "guide": f"{base}/{code}.xml.gz",
        "without_guide": build.placeholders,
        "unverified": sum(1 for e in build.entries if _reason(e) == "unverified"),
        "checked_in_country": build.confirmed,
        "build": {
            "sources": build.pulled,
            "ingested": build.ingested,
            "guides_matched": build.guides_matched,
            "guides_extended": build.guides_extended,
            "topped_up": build.topped_up,
            "no_guide": build.unlisted,
            "unavailable": build.unavailable,
            "guides_failed": build.guides_failed,
            "removed": {why: len(chs) for why, chs in build.removed.items() if chs},
            "merged": sum(len(d.dropped) for d in build.duplicates),
            "series": build.loops,
            "logos": sum(1 for e in build.entries if e.channel.logo),
            "programmes": sum(len(e.channel.programs) for e in build.entries),
        },
        "removed": [
            {
                "name": c.name,
                "source": c.source,
                "why": why if not c.report or c.report.ok else c.report.label,
            }
            for why, channels in build.removed.items()
            for c in channels
        ],
        "channels": [
            {
                "number": e.number,
                "name": e.channel.name,
                "group": build.group_name(e),
                "logo": e.channel.logo,
                "quality": e.channel.report.label if e.channel.report else None,
                "unverified": _reason(e) == "unverified",
            }
            for e in build.entries
        ],
    }


ORDER = ["ca", "us", "uk", "au", "nz"]


def _regions(site: Path) -> list[dict]:
    regions = []
    paths = sorted(site.glob("*.json"), key=lambda p: (ORDER + [p.stem]).index(p.stem))
    for path in paths:
        data = json.loads(path.read_text())
        if "channels" in data and "code" in data:
            regions.append(data)
    return regions


CODES = {"uk": "UK"}


def render_index(regions: list[dict], base: str) -> str:
    rows = "\n".join(_row(r) for r in regions)
    newest = max((r["updated"] for r in regions), default=0)
    updated = f'<time data-ts="{newest}">recently</time>' if newest else "soon"
    page = resources.files("openm3u.templates").joinpath("index.html").read_text()
    for key, value in {
        "{{regions}}": rows or "<li>No countries published yet.</li>",
        "{{updated}}": updated,
        "{{repo}}": REPO,
        "{{base}}": base,
    }.items():
        page = page.replace(key, value)
    return page


def _row(region: dict) -> str:
    name = escape(region["name"])
    code = CODES.get(region["code"], region["code"].upper())
    groups: dict[str, list[dict]] = {}
    for channel in region["channels"]:
        groups.setdefault(channel["group"], []).append(channel)
    return f"""<li class="region">
  <div class="region-head">
    <span class="code">{code}</span>
    <h3>{name}</h3>
    <span class="count">{len(region["channels"])} channels</span>
  </div>
  <div class="indent">
    <div class="copy">
      <input readonly aria-label="{name} playlist link" value="{escape(region["playlist"])}">
      <button type="button">Copy</button>
    </div>
    <div class="folds">
      <details class="fold">
        <summary>Lineup <b>{len(groups)} groups</b></summary>
        <div class="panel"><div class="groups">{_groups(groups)}</div></div>
      </details>
      <details class="fold">
        <summary>Guide (EPG)</summary>
        <div class="panel">
          <p>Already linked inside the playlist, so most apps load it on their own. Add it by hand
          only if your app asks for an EPG.</p>
          <div class="copy">
            <input readonly aria-label="{name} guide link" value="{escape(region["guide"])}">
            <button type="button">Copy</button>
          </div>
        </div>
      </details>
      <details class="fold">
        <summary>Build report</summary>
        <div class="panel">{_report(region)}</div>
      </details>
    </div>
  </div>
</li>"""


def _groups(groups: dict[str, list[dict]]) -> str:
    parts = []
    for group, channels in groups.items():
        span = _span([c["number"] for c in channels])
        items = "".join(f"<li><span>{c['number']}</span>{escape(c['name'])}</li>" for c in channels)
        parts.append(
            f'<details class="fold group"><summary><span>{escape(group)}</span>'
            f'<span class="range">{span}</span><span class="n">{len(channels)}</span></summary>'
            f"<ol>{items}</ol></details>"
        )
    return "".join(parts)


def _span(numbers: list[int]) -> str:
    """A group's numbers as ranges, one per tier: 400–499, 2400–2415."""
    low = min(numbers)
    tiers: dict[int, list[int]] = {}
    for number in sorted(numbers):
        tiers.setdefault((number - low) // OVERFLOW, []).append(number)
    return ", ".join(f"{t[0]}" if t[0] == t[-1] else f"{t[0]}–{t[-1]}" for t in tiers.values())


def _report(region: dict) -> str:
    stats = region.get("build")
    code = region["code"]
    if not stats:
        return "<p>No build report yet.</p>"

    def line(verb: str, text: str) -> str:
        return f'<span class="k">{verb:<7}</span>{escape(text)}'

    width = max((len(s) for s in stats["sources"]), default=8) + 2
    lines = [f'<span class="p">$</span> openm3u publish --region {code}']
    lines += [line("pull", f"{s:<{width}}{n:>5} channels") for s, n in stats["sources"].items()]
    lines.append(line("test", f"{stats['ingested']} streams"))
    lines += [line("drop", f"{n:>4} {why}") for why, n in stats["removed"].items()]
    if stats["merged"]:
        lines.append(line("merge", f"{stats['merged']:>4} duplicates"))
    if stats["series"]:
        lines.append(line("shelve", f"{stats['series']:>4} one-show channels into Series"))
    lines.append(line("write", f"{code}.m3u     {len(region['channels'])} channels"))
    lines.append(line("write", f"{code}.xml.gz  {stats['programmes']:,} listings"))
    if region.get("without_guide"):
        lines.append(line("note", f"{region['without_guide']} channels without a published guide"))
    if region.get("unverified"):
        unchecked = region["unverified"]
        lines.append(line("note", f"{unchecked} region-limited streams not yet checked in-country"))
    if region.get("checked_in_country"):
        confirmed = region["checked_in_country"]
        lines.append(
            line("note", f"{confirmed} region-limited streams confirmed from inside {code.upper()}")
        )
    stamp = f'<time data-ts="{region["updated"]}">recently</time>'
    lines.append(f'<span class="k">done   </span>{stamp}')
    return '<pre class="term">' + "\n".join(lines) + "</pre>"
