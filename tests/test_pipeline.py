import gzip
import json
import xml.etree.ElementTree as ET
from datetime import timedelta
from itertools import pairwise

import httpx

from openm3u.checks import Check, Checks
from openm3u.models import Program
from openm3u.pipeline import fill, run, summary, write
from openm3u.settings import Settings
from openm3u.site import publish
from openm3u.sources import Source

from .conftest import MIRRORS
from .factories import T0, channel, schedule

MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={res}\nv.m3u8\n"
MEDIA = "#EXTM3U\n#EXTINF:6,\ns.ts\n"


class Fake(Source):
    def __init__(self, name, channels, require_guide=False):
        super().__init__()
        self.name = name
        self._channels = channels
        self.require_guide = require_guide

    def channels(self):
        return self._channels


def stream(name, label=None, programs=(), source="fake", number=None):
    slug = name.lower().replace(" ", "-")
    return channel(
        name,
        source,
        label,
        number=number,
        programs=programs or schedule("Show A", "Show B", "Show C", "Show D"),
        url=f"https://streams.example/{slug}/master.m3u8",
    )


def lineup():
    return [
        stream("CBC News", "News & Opinion", schedule("The National") * 1),
        stream("CBS News Now", "News & Opinion"),
        stream("Global News BC", "Local News"),
        stream("Bloomberg", "News & Opinion"),
        stream("NFL Channel", "Sports"),
        stream("Weather Now", "Weather"),
        stream("Ink Master", "Reality", schedule(*["Ink Master"] * 10)),
        stream("Arthur", "Kids", schedule(*["Arthur"] * 10)),
        stream("Reality One", "Reality"),
        stream("Reality Two", "Reality"),
        stream("Kids One", "Kids"),
        stream("Kids Two", "Kids"),
        stream("Shop Now", "Shopping"),
        stream(
            "Télé Jeunesse",
            "Kids",
            [
                *schedule("Les aventures de Tintin", "Caillou"),
            ],
        ),
        stream("Radio-Canada INFO", "News & Opinion"),
        stream("Ici Télé", "Entertainment"),
    ]


def server(dead=(), drm=(), geo=(), low=()):
    def handler(request):
        slug = request.url.path.split("/")[1]
        if slug in dead:
            return httpx.Response(404)
        if slug in geo:
            return httpx.Response(403)
        if request.url.path.endswith("master.m3u8"):
            res = "960x540" if slug in low else "1920x1080"
            return httpx.Response(200, text=MASTER.format(bw=4_000_000, res=res))
        if request.url.path.endswith("v.m3u8"):
            key = '#EXT-X-KEY:METHOD=SAMPLE-AES,KEYFORMAT="com.widevine"\n' if slug in drm else ""
            return httpx.Response(200, text=MEDIA.replace("#EXTINF", key + "#EXTINF"))
        return httpx.Response(200, content=b"\x47" * 188)

    return httpx.Client(transport=httpx.MockTransport(handler))


def settings(tmp_path, **extra):
    return Settings(
        region="ca",
        output_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        checks_dir=tmp_path / "checks",
        guide_hours=24,
        mirrors=MIRRORS,
        **extra,
    )


def build(tmp_path, channels=None, client=None, **extra):
    return run(
        settings(tmp_path, **extra),
        sources={"fake": Fake("fake", channels or lineup())},
        use_tmdb=False,
        client=client or server(),
        now=T0,
    )


def by_name(result):
    return {e.channel.name: e for e in result.entries}


def test_end_to_end_lineup(tmp_path):
    result = build(tmp_path, client=server(dead={"cbs-news-now"}, drm={"nfl-channel"}))
    found = by_name(result)

    assert "CBS News Now" not in found
    assert "NFL Channel" not in found
    assert [c.name for c in result.removed["drm"]] == ["NFL Channel"]
    assert [c.name for c in result.removed["shopping"]] == ["Shop Now"]

    assert found["CBC News"].group == "news"
    assert 100 <= found["CBC News"].number < 200
    assert found["Weather Now"].group == "news"
    assert found["Ink Master"].group == "series"
    assert found["Arthur"].group == "series"
    series = sorted((e.number, e.channel.name) for e in result.entries if e.group == "series")
    assert [n for n, _ in series] == [1100, 1101]
    assert [name for _, name in series] == ["Arthur", "Ink Master"]

    numbers = [e.number for e in result.entries]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)

    text = summary(result)
    assert "removed    1  drm" in text
    assert "one-show loops into their own group" in text


def test_dead_streams_are_reported(tmp_path):
    result = build(tmp_path, client=server(dead={"cbs-news-now"}))
    assert [c.name for c in result.removed["dead"]] == ["CBS News Now"]


def test_hide_mode_drops_loops(tmp_path):
    result = build(tmp_path, single_show="hide")
    assert "Ink Master" not in by_name(result)
    assert "Ink Master" in {c.name for c in result.removed["one-show loops"]}


def test_rebuild_keeps_numbers(tmp_path):
    first = {e.channel.name: e.number for e in build(tmp_path).entries}
    second = build(tmp_path, client=server(dead={"cbc-news"}))
    assert all(first[e.channel.name] == e.number for e in second.entries)


def test_written_files_load(tmp_path):
    result = build(tmp_path)
    playlist, guide = write(result, tmp_path / "out", "https://tv.example/ca.xml.gz")
    text = playlist.read_text()
    assert text.count("#EXTINF") == len(result.entries)
    assert 'group-title="News"' in text
    assert "https://streams.example/cbc-news/master.m3u8" in text
    root = ET.fromstring(gzip.decompress(guide.read_bytes()))
    assert len(root.findall("channel")) == len(result.entries)
    assert root.findall("programme")


def test_hd_floor_drops_lower_resolution_channels(tmp_path):
    result = build(tmp_path, client=server(low={"weather-now"}))
    assert [c.name for c in result.removed["below 720p"]] == ["Weather Now"]
    assert all(e.channel.report.height >= 720 for e in result.entries)


def test_other_languages_get_their_own_block(tmp_path):
    found = by_name(build(tmp_path))
    for name in ("Radio-Canada INFO", "Télé Jeunesse"):
        assert found[name].group == "lang-fr"
        assert found[name].number >= 1400
    assert all(e.channel.language == "en" for e in found.values() if e.group != "lang-fr")


def test_sources_without_a_guide_need_one_unless_curated(tmp_path):
    listed = stream("Listed", "Reality", source="strict")
    bare = stream("Bare", "Reality", source="strict")
    bare.programs = []
    curated = stream("Picked", "Reality", source="strict")
    curated.programs, curated.curated = [], True
    result = run(
        settings(tmp_path),
        sources={
            "fake": Fake("fake", lineup()),
            "strict": Fake("strict", [listed, bare, curated], require_guide=True),
        },
        use_tmdb=False,
        client=server(),
        now=T0,
    )
    found = by_name(result)
    assert "Listed" in found and "Picked" in found
    assert [c.name for c in result.removed["no guide"]] == ["Bare"]
    assert found["Picked"].channel.programs[0].title == "Picked"
    assert result.placeholders == 1


def test_away_from_home_a_refusal_is_inconclusive(tmp_path):
    result = build(tmp_path, client=server(geo={"cbc-news"}), runs_in="us")
    assert by_name(result)["CBC News"].channel.report.reason == "unverified"
    at_home = build(tmp_path, client=server(geo={"cbc-news"}), runs_in="ca")
    assert "CBC News" not in by_name(at_home)


def test_in_country_checks_settle_unverified_streams(tmp_path):
    now = (T0 - timedelta(days=2)).timestamp()
    checks = Checks(
        "ca",
        "ca",
        {
            "https://streams.example/cbc-news/master.m3u8": Check(
                "CBC News", True, "720p", 720, now
            ),
            "https://streams.example/kids-one/master.m3u8": Check(
                "Kids One", False, "http 404", 0, now
            ),
        },
    )
    checks.save(tmp_path / "checks" / "ca.json")
    result = build(tmp_path, client=server(geo={"cbc-news", "kids-one"}), runs_in="us")
    found = by_name(result)
    assert found["CBC News"].channel.report.reason == "checked in CA"
    assert "Kids One" not in found
    assert [c.name for c in result.removed["failed in CA"]] == ["Kids One"]
    assert result.confirmed == 1

    stale = (T0 - timedelta(days=30)).timestamp()
    for check in checks.streams.values():
        check.when = stale
    checks.save(tmp_path / "checks" / "ca.json")
    result = build(tmp_path, client=server(geo={"cbc-news", "kids-one"}), runs_in="us")
    assert by_name(result)["Kids One"].channel.report.reason == "unverified"


def test_full_canada_publish_from_real_feeds(tmp_path):
    result = run(
        Settings(
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            mirrors=MIRRORS,
            public_url="https://example.test/tv",
        ),
        check_health=False,
        use_tmdb=False,
        now=T0.replace(hour=11),
    )
    found = by_name(result)

    assert "CBC Vancouver" not in found
    assert "CBC Vancouver" in {c.name for c in result.removed["hidden"]}
    assert found["CBC News Network"].group == "news"
    assert found["CTV News"].group == "news"
    assert found["CBC News"].channel.source == "samsung"
    assert found["Radio-Canada INFO"].group == "lang-fr"
    assert found["Ici Radio-Canada Télé Ontario"].group == "lang-fr"
    assert found["Ink Master"].group == "series"
    assert found["CBC News Network"].channel.programs[0].title == "Power & Politics"
    assert found["CPAC"].channel.programs[0].title == "CPAC"
    assert result.unavailable == ["world"]
    assert found["CTV News"].channel.logo.endswith("/countries/canada/ctv-news-ca.png")
    assert "5AAB TV" in {c.name for c in result.removed["blocklisted"]}

    files = publish(result, tmp_path / "site", "https://example.test/tv", domain="openm3u.tv")
    playlist = files[0].read_text()
    assert 'x-tvg-url="https://example.test/tv/ca.xml.gz"' in playlist
    assert "https://jmp2.uk/stvp-CA1400004AE" in playlist
    site = tmp_path / "site"
    status = json.loads((site / "ca.json").read_text())
    assert status["playlist"] == "https://example.test/tv/ca.m3u"
    assert {c["group"] for c in status["channels"]} >= {"News", "Series", "En français"}
    index = (site / "index.html").read_text()
    assert "https://example.test/tv/ca.m3u" in index
    assert "open<span>m3u</span>.tv" in index
    assert "CBC News Network" in index
    assert (site / "CNAME").read_text() == "openm3u.tv\n"
    assert (site / "favicon.png").exists() and (site / "og.png").exists()


def test_the_whole_window_is_covered_with_no_silent_slots():

    start = T0.replace(minute=20)
    stop = start + timedelta(hours=6)
    short = channel("Samsung Thing")
    short.programs = [
        Program(T0, T0 + timedelta(minutes=50), "First"),
        Program(T0 + timedelta(hours=2), T0 + timedelta(hours=3), "Second"),
    ]
    added = fill(short, start, stop)
    titles = [(p.start.strftime("%H:%M"), p.title) for p in short.programs]
    assert titles == [
        ("06:00", "First"),
        ("06:50", "Samsung Thing"),
        ("07:00", "Samsung Thing"),
        ("08:00", "Second"),
        ("09:00", "Samsung Thing"),
        ("10:00", "Samsung Thing"),
        ("11:00", "Samsung Thing"),
        ("12:00", "Samsung Thing"),
    ]
    assert added == 6
    assert short.programs[-1].stop == stop

    empty = channel("No Guide")
    fill(empty, start, stop)
    assert empty.programs[0].start == T0 and empty.programs[-1].stop == stop
    assert all(a.stop == b.start for a, b in pairwise(empty.programs))
