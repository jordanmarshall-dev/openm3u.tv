from datetime import timedelta

import httpx

from openm3u.models import Program
from openm3u.tmdb import Tmdb, enrich

from .factories import T0

GENRES = {"genres": [{"id": 28, "name": "Action"}, {"id": 35, "name": "Comedy"}]}
SEARCH = {
    ("movie", "Heat"): [
        {"id": 1, "title": "Heat", "release_date": "1986-07-11", "popularity": 3},
        {
            "id": 949,
            "title": "Heat",
            "release_date": "1995-12-15",
            "overview": "A cop and a thief.",
            "poster_path": "/heat.jpg",
            "backdrop_path": "/heat_wide.jpg",
            "genre_ids": [28],
            "popularity": 40,
        },
    ],
    ("tv", "Frasier"): [
        {
            "id": 3452,
            "name": "Frasier",
            "first_air_date": "1993-09-16",
            "overview": "Radio shrink.",
            "poster_path": "/frasier.jpg",
            "backdrop_path": None,
            "genre_ids": [35],
        },
    ],
    ("tv", "Totally Unknown Show"): [
        {"id": 7, "name": "Something Else Entirely", "first_air_date": "2001-01-01"},
    ],
}


def make_client(calls):
    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.startswith("/3/genre/"):
            return httpx.Response(200, json=GENRES)
        kind = path.rsplit("/", 1)[-1]
        results = SEARCH.get((kind, request.url.params["query"]), [])
        return httpx.Response(200, json={"results": results})

    return httpx.Client(transport=httpx.MockTransport(handler))


def program(title, kind=None, year=None, **extra):
    return Program(T0, T0 + timedelta(hours=1), title, kind=kind, year=year, **extra)


def test_movie_match_respects_year(tmp_path):
    tmdb = Tmdb("abc", tmp_path / "tmdb.json", make_client([]))
    match = tmdb.lookup("movie", "Heat", 1995)
    assert match.id == 949
    assert match.genres == ["Action"]
    assert match.backdrop.endswith("/w780/heat_wide.jpg")


def test_unrelated_results_are_rejected(tmp_path):
    tmdb = Tmdb("abc", tmp_path / "tmdb.json", make_client([]))
    assert tmdb.lookup("tv", "Totally Unknown Show") is None


def test_lookups_are_cached_on_disk(tmp_path):
    calls = []
    first_run = Tmdb("abc", tmp_path / "tmdb.json", make_client(calls))
    first_run.lookup("tv", "Frasier")
    first_run.save()
    first = len(calls)
    tmdb = Tmdb("abc", tmp_path / "tmdb.json", make_client(calls))
    enrich([program("Frasier", "episode")], tmdb)
    assert len(calls) == first


def test_bearer_tokens_go_in_the_header(tmp_path):
    calls = []
    Tmdb("eyJhbGciOi.token", tmp_path / "t.json", make_client(calls)).lookup("tv", "Frasier")
    assert calls[0].headers["authorization"] == "Bearer eyJhbGciOi.token"
    assert "api_key" not in calls[0].url.params


def test_enrich_fills_gaps_without_clobbering_episode_detail(tmp_path):
    tmdb = Tmdb("abc", tmp_path / "tmdb.json", make_client([]))
    heat = program("Heat", "movie", 1995)
    frasier = program(
        "Frasier",
        "episode",
        description="Niles buys a painting.",
        art="https://images.pluto.tv/blurry.jpg",
    )
    unknown = program("Totally Unknown Show")
    enrich([heat, frasier, unknown], tmdb, art="landscape")

    assert heat.art.endswith("/heat_wide.jpg")
    assert heat.description == "A cop and a thief."
    assert heat.categories == ["Action"]
    assert frasier.description == "Niles buys a painting."
    assert frasier.art.endswith("/w500/frasier.jpg")
    assert unknown.art is None
