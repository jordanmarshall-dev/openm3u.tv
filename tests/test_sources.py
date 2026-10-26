from datetime import UTC, datetime, timedelta

from openm3u.fetch import Fetcher
from openm3u.guide import read_guide, tidy
from openm3u.guides import borrow, match_guides
from openm3u.models import Program
from openm3u.regions import CODES, load_region
from openm3u.sources import Database, Fast, FreeToAir, IptvOrg, Playlist, build_source
from openm3u.sources.playlist import parse_m3u

from .conftest import FIXTURES, IPTV_ORG, MIRRORS

NOW = datetime(2026, 10, 24, 11, tzinfo=UTC)
EPGSHARE = str(FIXTURES / "epgshare-ca.xml")


def fetcher():
    return Fetcher(mirrors=MIRRORS)


def by_name(channels):
    return {c.name: c for c in channels}


def iptv_org(**extra):
    return IptvOrg("iptv-org", "CA", ["ca"], fetcher(), Database(fetcher()), **extra)


def test_fast_services_play_through_jmp2_and_drop_drm():
    samsung = Fast("samsung", "samsung", "ca", fetcher())
    channels = by_name(samsung.channels())
    assert "Locked Channel" not in channels
    assert [c.name for c in samsung.removed["drm"]] == ["Locked Channel"]
    ctv = channels["CTV News"]
    assert ctv.labels == ["News & Opinion"]
    assert ctv.url == "https://jmp2.uk/stvp-CA1400004AE"

    pluto = Fast("pluto", "pluto", "ca", fetcher())
    cops = by_name(pluto.channels())["COPS"]
    assert cops.url == f"https://jmp2.uk/plu-{cops.source_id}.m3u8"


def test_fast_guide_is_trimmed_to_the_window():
    pluto = Fast("pluto", "pluto", "ca", fetcher())
    channels = pluto.channels()
    pluto.schedule(channels, NOW, NOW + timedelta(hours=6))
    ink = by_name(channels)["Ink Master"]
    assert ink.programs
    assert all(p.stop > NOW and p.start < NOW + timedelta(hours=6) for p in ink.programs)
    assert ink.programs[0].season and ink.programs[0].kind == "episode"


def test_free_to_air_keeps_numbers_headers_and_skips_drm():
    nz = FreeToAir("freeview", "nz", fetcher())
    channels = by_name(nz.channels())
    assert "TVNZ 1" in {c.name for c in nz.removed["drm"]}
    three = channels["Three"]
    assert (three.number, three.labels) == (3, ["Free to air"])
    assert three.url == "https://i.mjh.nz/nz/three.m3u8"
    assert three.headers["user-agent"].startswith("otg/")
    assert "referer" not in three.headers
    assert channels["Al Jazeera"].labels == []

    nz.schedule(list(channels.values()), NOW - timedelta(hours=1), NOW + timedelta(hours=6))
    assert [p.title for p in channels["Al Jazeera"].programs] == ["Newshour"]


def test_m3u_entries_lose_tags_resolution_and_call_signs():
    entries = parse_m3u((FIXTURES / "iptv-org-ca.m3u").read_text())
    five = entries[0]
    assert five.name == "5AAB TV"
    assert five.tags == {"not 24/7"}
    assert five.height == 720
    toronto = entries[2]
    assert (toronto.name, toronto.call_sign) == ("CBC Toronto", "CBLT")
    french = entries[6]
    assert (french.name, french.call_sign) == ("Ici Radio-Canada Télé Ontario", "CBLFT")


def test_plain_playlist_applies_include_rules():
    playlist = Playlist(
        "community",
        f"{IPTV_ORG}/ca.m3u",
        fetcher(),
        include={"CBC News*": "News", "TVOKids*": "Kids"},
    )
    channels = playlist.channels()
    assert [c.name for c in channels] == ["CBC News Network", "TVOKids", "TVOKids"]
    assert all(c.curated for c in channels)
    assert channels[0].labels == ["News"]
    assert len({c.source_id for c in channels}) == 3


def test_iptv_org_reads_the_database():
    source = iptv_org()
    channels = by_name(source.channels())
    assert [c.name for c in source.removed["blocklisted"]] == ["5AAB TV"]

    toronto = channels["CBC Toronto"]
    assert toronto.labels == ["local"]
    assert toronto.area == "Toronto"
    assert toronto.call_sign == "CBLT"
    assert toronto.language == "en"
    assert toronto.guide_id == "CBCTelevision.ca@CBLTDT"
    assert not toronto.curated

    assert channels["CBC News Network"].labels == ["news"]
    assert channels["CBC News Network"].area == ""
    assert channels["CPAC"].labels == ["legislative"]
    assert channels["Ici Radio-Canada Télé Ontario"].language == "fr"


def test_iptv_org_include_rules_curate_by_name():
    source = iptv_org(include={"CPAC*": "News"})
    cpac = by_name(source.channels())["CPAC"]
    assert cpac.curated and cpac.labels == ["News"]


def test_guides_match_by_id_call_sign_and_name():
    channels = iptv_org().channels()
    matched = match_guides(
        channels,
        ["/nope/missing.xml", EPGSHARE],
        fetcher(),
        NOW,
        NOW + timedelta(hours=12),
        names={"CPAC": "CPAC Ottawa"},
    )
    found = by_name(channels)
    assert matched == (4, 0)
    vancouver = found["CBC Vancouver"]
    assert [p.title for p in vancouver.programs] == ["Vancouver News at 6"]
    assert vancouver.logo == "https://logos.example/cbc.png"
    assert len(found["CBC Toronto"].programs) == 2
    assert found["CBC News Network"].programs[0].title == "Power & Politics"
    assert found["CPAC"].programs[0].title == "Question Period"


def test_guide_ids_with_dots_and_suffixes_match_by_name(tmp_path):
    ids = ["CBC.Vancouver.HD.ca2", "CBC.Winnipeg.ca2", "CBC.News.Network.ca2"]
    channels_xml = "".join(
        f'<channel id="{i}"><display-name>{i}</display-name></channel>' for i in ids
    )
    programmes = "".join(
        f'<programme channel="{i}" start="20261024110000 +0000" stop="20261024120000 +0000">'
        f"<title>On {i}</title></programme>"
        for i in ids
    )
    guide = tmp_path / "ca2.xml"
    guide.write_text(f"<tv>{channels_xml}{programmes}</tv>")
    playlist = tmp_path / "ca.m3u"
    playlist.write_text(
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-id="x",CBC Vancouver\nhttps://e.test/a.m3u8\n'
        '#EXTINF:-1 tvg-id="y",CBC Manitoba\nhttps://e.test/b.m3u8\n'
        '#EXTINF:-1 tvg-id="z",CBC News Network\nhttps://e.test/c.m3u8\n'
    )
    channels = Playlist("p", str(playlist), Fetcher()).channels()
    match_guides(
        channels,
        [str(guide)],
        Fetcher(),
        NOW,
        NOW + timedelta(hours=6),
        names={"CBC Manitoba": "CBC Winnipeg"},
    )
    titles = {c.name: c.programs[0].title for c in channels}
    assert titles == {
        "CBC Vancouver": "On CBC.Vancouver.HD.ca2",
        "CBC Manitoba": "On CBC.Winnipeg.ca2",
        "CBC News Network": "On CBC.News.Network.ca2",
    }


def test_stations_without_listings_borrow_a_siblings_guide():
    channels = by_name(iptv_org().channels())
    vancouver, toronto = channels["CBC Vancouver"], channels["CBC Toronto"]
    vancouver.programs = [Program(NOW, NOW + timedelta(hours=1), "Vancouver News at 6")]
    assert borrow(list(channels.values()), {"CBC Toronto": "CBC Vancouver"}) == 1
    assert toronto.programs[0].title == "Vancouver News at 6"
    assert toronto.programs[0] is not vancouver.programs[0]


def test_guide_reader_handles_episode_numbers_kinds_and_windows():
    xml = b"""<tv><channel id="a"><display-name>A</display-name></channel>
    <programme channel="a" start="20261024100000 +0000" stop="20261024110000 +0000">
      <title>Frasier</title><episode-num system="xmltv_ns">2.4.</episode-num>
      <category>Series</category><category>Comedy</category><date>1995</date>
    </programme>
    <programme channel="a" start="20261024110000 +0000" stop="20261024130000 +0000">
      <title>Heat</title><category>Movie</category><icon src="https://img/heat.jpg"/>
    </programme></tv>"""
    guide = read_guide(xml)
    frasier, heat = guide.programs["a"]
    assert (frasier.season, frasier.episode, frasier.kind) == (3, 5, "episode")
    assert frasier.categories == ["Comedy"]
    assert heat.kind == "movie" and heat.art == "https://img/heat.jpg"
    assert guide.names["a"] == ["A"]
    later = read_guide(xml, NOW, NOW + timedelta(hours=3))
    assert [p.title for p in later.programs["a"]] == ["Heat"]


def test_episode_numbers_glued_to_titles_are_pulled_out():
    program = tidy(Program(NOW, NOW, "The 100. S01E09"))
    assert (program.title, program.season, program.episode) == ("The 100", 1, 9)
    assert tidy(Program(NOW, NOW, "S.W.A.T.")).title == "S.W.A.T."
    assert tidy(Program(NOW, NOW, "Survivor - S12 E3")).title == "Survivor"
    heat = tidy(Program(NOW, NOW, "Heat (1995)", kind="movie"))
    assert (heat.title, heat.year) == ("Heat", 1995)
    assert tidy(Program(NOW, NOW, "(2012)")).title == "(2012)"


def test_every_region_builds_its_sources():
    database = Database(fetcher())
    for code in CODES:
        region = load_region(code)
        names = [build_source(spec, fetcher(), database).name for spec in region.sources]
        assert len(names) == len(set(names)), code
        assert region.taxonomy.has(region.taxonomy.fallback)
        assert region.group(region.taxonomy.series).keep_small


def test_city_government_channels_are_public_access(tmp_path):
    db = tmp_path / "db"
    db.mkdir()
    for name in ("channels", "feeds", "blocklist", "subdivisions", "cities"):
        (db / f"{name}.csv").write_text((FIXTURES / "iptv-org-db" / f"{name}.csv").read_text())
    with (db / "channels.csv").open("a") as f:
        f.write("CouncilTV.ca,Council TV,,,,CA,legislative,FALSE,,,,\n")
    with (db / "feeds.csv").open("a") as f:
        f.write("CouncilTV.ca,SD,SD,,TRUE,ct/CAVAN,America/Vancouver,eng,720p\n")
    playlist = tmp_path / "ca.m3u"
    playlist.write_text(
        '#EXTM3U\n#EXTINF:-1 tvg-id="CouncilTV.ca@SD",Council TV\nhttps://e.test/c.m3u8\n'
        '#EXTINF:-1 tvg-id="CPACEnglish.ca@SD",CPAC\nhttps://e.test/p.m3u8\n'
    )
    mirrors = {IPTV_ORG: str(tmp_path), "https://db.test": str(db)}
    source = IptvOrg(
        "iptv-org",
        "CA",
        ["ca"],
        Fetcher(mirrors=mirrors),
        Database(Fetcher(mirrors=mirrors), "https://db.test"),
    )
    channels = by_name(source.channels())
    assert channels["Council TV"].labels == ["public access"]
    assert channels["CPAC"].labels == ["legislative"]
    taxonomy = load_region("ca").taxonomy
    assert taxonomy.classify(channels["Council TV"].labels) == (None, "public access")
