import xml.etree.ElementTree as ET
from datetime import timedelta

from openm3u.models import Entry, Program
from openm3u.output import render_m3u, render_xmltv

from .factories import T0, channel


def entries():
    news = channel("CBC News", label="News + Opinion")
    news.logo = "https://img.example/cbc.png"
    news.programs = [
        Program(
            T0,
            T0 + timedelta(hours=1),
            "The National",
            description="Tonight's top stories",
            categories=["News"],
        )
    ]
    show = channel('Pluto TV "Comedy"')
    show.programs = [
        Program(
            T0,
            T0 + timedelta(minutes=30),
            "Frasier",
            subtitle="The Good Son",
            season=1,
            episode=1,
            kind="episode",
            art="https://img.example/f.jpg",
            rating="TV-PG",
        )
    ]
    movie = channel("Pluto TV Action Movies")
    movie.programs = [
        Program(T0, T0 + timedelta(hours=2), "Heat", kind="movie", year=1995),
        Program(T0 + timedelta(hours=2), T0 + timedelta(hours=4), "Knowing", kind="movie"),
    ]
    return [
        Entry(news, "cbc-news", "News", 100),
        Entry(show, "pluto-tv-comedy", "Comedy", 300),
        Entry(movie, "pluto-tv-action-movies", "Movies", 200),
    ]


def test_m3u_has_numbers_groups_and_guide_link():
    text = render_m3u(entries(), "ca", guide_url="http://box/ca.xml.gz")
    lines = text.splitlines()
    assert lines[0] == '#EXTM3U x-tvg-url="http://box/ca.xml.gz" url-tvg="http://box/ca.xml.gz"'
    assert lines[1] == (
        '#EXTINF:-1 tvg-id="cbc-news.ca" tvg-chno="100" tvg-name="CBC News" '
        'tvg-logo="https://img.example/cbc.png" group-title="News",CBC News'
    )
    assert lines[2] == "https://streams.example/pluto/cbc-news.m3u8"
    assert "tvg-name=\"Pluto TV 'Comedy'\"" in lines[3]


def test_xmltv_is_valid_and_complete():
    root = ET.fromstring(render_xmltv(entries(), "ca"))
    assert [c.get("id") for c in root.iter("channel")] == [
        "cbc-news.ca",
        "pluto-tv-comedy.ca",
        "pluto-tv-action-movies.ca",
    ]

    programmes = {p.findtext("title"): p for p in root.iter("programme")}
    assert "Heat (1995)" in programmes
    assert "Knowing (???)" in programmes
    frasier = programmes["Frasier"]
    assert frasier.get("start") == "20261024060000 +0000"
    assert frasier.find("sub-title") is None
    assert frasier.findtext("desc") == "S01E01 · The Good Son"
    assert frasier.find("episode-num") is None
    assert frasier.find("icon").get("src") == "https://img.example/f.jpg"
    assert frasier.find("rating/value").text == "TV-PG"
    assert [c.text for c in frasier.findall("category")] == ["Series"]

    heat = programmes["Heat (1995)"]
    assert heat.findtext("date") == "1995"
    assert [c.text for c in heat.findall("category")] == ["Movie"]
    assert programmes["The National"].findtext("desc") == "Tonight's top stories"
