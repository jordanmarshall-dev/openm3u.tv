from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from .models import Program
from .text import fold

log = logging.getLogger(__name__)

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p"
MISS_TTL = 7 * 86400


@dataclass
class Match:
    id: int
    kind: str
    title: str
    year: int | None = None
    overview: str = ""
    poster: str | None = None
    backdrop: str | None = None
    genres: list[str] = field(default_factory=list)


class Tmdb:
    def __init__(self, key: str, cache_path: Path, client: httpx.Client | None = None):
        if key.startswith("eyJ"):
            headers, self._params = {"authorization": f"Bearer {key}"}, {}
        else:
            headers, self._params = {}, {"api_key": key}
        self.client = client or httpx.Client(timeout=20)
        self.client.headers.update(headers)
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        if cache_path.exists():
            self._cache = json.loads(cache_path.read_text())
        self._genres: dict[str, dict[int, str]] = {}
        self._lock = threading.Lock()

    def lookup(self, kind: str, title: str, year: int | None = None) -> Match | None:
        key = f"{kind}|{fold(title)}|{year or ''}"
        with self._lock:
            hit = self._cache.get(key)
        if hit and (hit["match"] or time.time() - hit["at"] < MISS_TTL):
            return Match(**hit["match"]) if hit["match"] else None

        match = self._search(kind, title, year)
        with self._lock:
            self._cache[key] = {"at": time.time(), "match": asdict(match) if match else None}
        return match

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache))

    def _search(self, kind: str, title: str, year: int | None) -> Match | None:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year" if kind == "movie" else "first_air_date_year"] = year
        results = self._get(f"/search/{kind}", params).get("results", [])
        if not results and year:
            params.pop("year", None)
            params.pop("first_air_date_year", None)
            results = self._get(f"/search/{kind}", params).get("results", [])

        best, best_score = None, 0.0
        for result in results[:10]:
            score = _score(kind, title, year, result)
            if score > best_score:
                best, best_score = result, score
        if best is None:
            return None

        genres = self._genre_names(kind)
        name_key, date_key = (
            ("title", "release_date") if kind == "movie" else ("name", "first_air_date")
        )
        return Match(
            id=best["id"],
            kind=kind,
            title=best.get(name_key) or title,
            year=_year(best.get(date_key)),
            overview=best.get("overview") or "",
            poster=f"{IMAGES}/w500{best['poster_path']}" if best.get("poster_path") else None,
            backdrop=f"{IMAGES}/w780{best['backdrop_path']}" if best.get("backdrop_path") else None,
            genres=[genres[g] for g in best.get("genre_ids", []) if g in genres],
        )

    def _genre_names(self, kind: str) -> dict[int, str]:
        if kind not in self._genres:
            rows = self._get(f"/genre/{kind}/list", {}).get("genres", [])
            self._genres[kind] = {g["id"]: g["name"] for g in rows}
        return self._genres[kind]

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(3):
            response = self.client.get(API + path, params={**self._params, **params})
            if response.status_code == 429:
                time.sleep(float(response.headers.get("retry-after", 1 + attempt)))
                continue
            response.raise_for_status()
            return response.json()
        return {}


def _score(kind: str, title: str, year: int | None, result: dict) -> float:
    names = {
        fold(result.get(k) or "") for k in ("title", "original_title", "name", "original_name")
    }
    names.discard("")
    wanted = fold(title)
    if wanted in names:
        score = 2.0
    else:
        ratio = max((SequenceMatcher(None, wanted, n).ratio() for n in names), default=0)
        if ratio < 0.92:
            return 0
        score = 1.0

    found = _year(result.get("release_date") or result.get("first_air_date"))
    if year and found:
        if abs(found - year) <= 1:
            score += 1
        elif kind == "movie":
            return 0
    return score + min(result.get("popularity", 0), 100) / 1000


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def enrich(programs: list[Program], tmdb: Tmdb, art: str = "landscape", workers: int = 4) -> int:
    def kind(p: Program) -> str:
        return "movie" if p.kind == "movie" else "tv"

    wanted = {(kind(p), p.title, p.year if p.kind == "movie" else None) for p in programs}

    def resolve(item):
        try:
            return item, tmdb.lookup(*item)
        except httpx.HTTPError as exc:
            log.warning("tmdb lookup failed for %s: %s", item[1], exc)
            return item, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = dict(pool.map(resolve, wanted))
    tmdb.save()

    enriched = 0
    for program in programs:
        match = found.get(
            (kind(program), program.title, program.year if program.kind == "movie" else None)
        )
        if not match:
            continue
        if art == "landscape":
            image = match.backdrop or match.poster
        else:
            image = match.poster or match.backdrop
        if image:
            program.art = image
        if not program.description and match.overview:
            program.description = match.overview
        if not program.categories:
            program.categories = list(match.genres)
        if program.kind == "movie" and not program.year:
            program.year = match.year
        enriched += 1
    log.info("tmdb: %d of %d titles matched", sum(1 for m in found.values() if m), len(found))
    return enriched
