# Handoff: Open M3U 1.0

This document is for whoever works on the codebase next. It covers what the project is, how the 1.0 code works, the decisions made along the way and why, and what's still open.

Maintainer: Jordan Marshall (GitHub `jordanmarshall-dev`).
First written October 24, 2026 at the end of the first build session (as Rabbit Ears); rewritten the same day after the 1.0 overhaul.

---

## 1. The vision

**Open M3U, at openm3u.tv.** The basic cable of IPTV.

A clean, organized playlist of the free, publicly available live channels in a country: something you could use to test an IPTV player, set up on a spare TV, or hand to someone who just wants free channels that work. Existing community lists are comprehensive but unsorted; Open M3U is the polished layer on top.

What that means in practice:

- **One playlist per country**, covering the free, publicly available live channels there, from every source worth using.
- **Organized like a cable package**: real channel numbers in genre blocks, the big broadcasters first, local news grouped by city, one-show channels shelved separately, other languages kept together.
- **Nothing broken**: every stream tested, dead and copy-protected ones removed, HD only.
- **A complete, clean guide (EPG)** matched to every channel.
- **The site is the product**: someone visits, copies a link, pastes it into TiviMate (or any IPTV app), done. The audience already knows what an M3U is; the site doesn't need to teach IPTV, just hand over a clean link.
- **No video is ever hosted.** The project is a curator: it publishes links to streams their owners serve publicly, like iptv-org does. This is a deliberate line. Don't host or relay streams, don't work around regional restrictions, don't include anything behind a login, subscription or DRM, and always honour removal requests.

### The rebrand

- Name: **Open M3U**. Domain: **openm3u.tv**, not registered yet as of October 24, 2026. Once it is, set `domain` in `site.toml` (section 9).
- Visual identity: the warm palette and the bold Outfit wordmark, now `openm3u.tv` with `m3u` in the orange accent. The owner's wordmark image is `docs/logo.png` (and `docs/logo-dark.png`); the site renders it as live text.
- Repo `jordanmarshall-dev/openm3u.tv`, package and CLI `openm3u`. The old repo name redirects.
- Names considered and rejected: rabbit-ears.tv (taken), openiptv.tv (too easily confused with paid IPTV services).

---

## 2. Where things stand

**Repo:** `jordanmarshall-dev/openm3u.tv` (renamed from `rabbit-ears`).
**Live site:** https://jordanmarshall-dev.github.io/openm3u.tv/ (GitHub Pages, deployed by GitHub Actions).
**Playlists:** `{site}/{ca,us,uk,au,nz}.m3u`, guides at the same paths with `.xml.gz`.
**Rebuilt** every three hours by `.github/workflows/publish.yml` (cron `17 */3 * * *`), plus manual runs.

The 1.0 overhaul was developed offline against clones of Matt's feeds, iptv-org's streams and its database (the sandbox can't reach epgshare01 or the streams themselves). Offline builds, before epgshare guides and before health checks, came out at roughly: Canada 491, US 933, UK 423, Australia 181, New Zealand 57. CI will differ: epgshare guides let more iptv-org channels in, and health checks drop dead ones.

Tests: 94, run in CI on Python 3.11, 3.12 and 3.13 with ruff lint and format checks.

---

## 3. How the code works

Python 3.11+, one dependency (`httpx`), in `src/openm3u/`.

### Pipeline (`pipeline.run`)

1. **Ingest.** Each source returns channels (with their stream URL) and usually their listings. A source that can't be reached is skipped and reported, not fatal. Channels still without listings are matched against the region's `guides` (by guide id, then call sign, then a configured name, then their own name), then may borrow a sibling station's listings (`guide_fallback`). Titles are tidied. Sources that can't vouch for their channels (iptv-org) drop any channel that found no guide, unless it was picked by name in the region file.
2. **Classify.** `taxonomy.toml` maps every label onto one shared set of groups. No useful label: the guide's categories decide by airtime, then name hints. Shopping, religion and adult labels are left out.
3. **Curate.** Hide lists (names, prefixes, or `*` patterns on names or source ids), one-show loops to Series (live groups exempt), other languages to their block or out.
4. **Health.** Every stream probed. Outside the builder's country, 401/403/451 means "unverified", and `checks/{code}.json` (written by `openm3u verify` from inside the country) settles those for 14 days. DRM, dead and below-720p are dropped.
5. **Dedupe, logos, lineup, numbers, TMDB, placeholders, publish**, as before.

### Modules

| Module | Job |
|---|---|
| `cli.py` | `build`, `publish`, `verify`, `categories`, `probe` |
| `settings.py` | User and site settings (`openm3u.toml`, `site.toml`) |
| `regions/__init__.py` + `regions/*.toml` | Region loading; each country's editorial choices |
| `taxonomy.py` + `taxonomy.toml` | The shared groups, numbering and label map |
| `sources/mjh.py` | `Fast` (Samsung, Pluto via jmp2.uk) and `FreeToAir` (Matt's AU/NZ/world feeds) |
| `sources/iptvorg.py` | iptv-org stream files plus its database (categories, languages, areas, NSFW, closed, blocklist) |
| `sources/playlist.py` | M3U parsing and a generic M3U source |
| `guide.py` / `guides.py` | XMLTV reading (windowed) / matching channels to guides |
| `filters.py`, `language.py`, `dedupe.py`, `logos.py` | Curation steps |
| `health.py`, `checks.py` | Stream probing, in-country check records |
| `lineup.py`, `state.py` | Groups, ordering, stable numbers |
| `output/`, `site.py`, `templates/` | Writers and the public site |
| `tmdb.py`, `fetch.py` | Optional artwork; fetching with `mirrors` for offline runs |

### Region files

A region lists its sources (priority order), `guides`, `featured` patterns, `places` (west to east for Canada; matched against names and iptv-org broadcast areas), `aliases`, `hide`, `guide_names`, `guide_fallback`, `[[languages]]` blocks, and `[groups.<id>]` overrides (`name`, `start`, `size`, `sort`, `keep_numbers`, `drop`). A `[labels]` table can send a label (or `source:label`) to another group or to `skip:<reason>`. Nothing else is per-region any more.

### Offline builds

```toml
[mirrors]
"https://i.mjh.nz" = "/path/to/matthuisman/i.mjh.nz"
"https://raw.githubusercontent.com/iptv-org/iptv/master/streams" = "/path/to/iptv-org/iptv/streams"
"https://raw.githubusercontent.com/iptv-org/database/master/data" = "/path/to/iptv-org/database/data"
"https://api.github.com/repos/tv-logo/tv-logos/git/trees/main?recursive=1" = "/path/to/tree.json"
```

Then `openm3u -c dev.toml publish --region ca --site site --skip-health --skip-tmdb`.

### Stable numbering

Numbers persist in `state/{code}.json`, published with the site and pulled back by CI before each build (`public_url`, then `previous_url`). A channel keeps its number while it stays in its group; vanished numbers are held 30 days. Bump a region's `layout` when groups move. Canada is on layout 2; the others kept layout 1 so their numbers carry over.

---

## 4. Sources and what we learned about each

| Source | Used for | Notes |
|---|---|---|
| **Matt Huisman, i.mjh.nz** (`github.com/matthuisman/i.mjh.nz`) | Samsung TV Plus and Pluto TV channel lists and guides for CA, US, GB; AU and NZ free-to-air; Plex and Roku guides | The backbone. `.channels.json.gz` per service holds every region; `{region}.xml.gz` is the guide. Samsung's JSON has a `slug` field (`stvp-{id}`); Pluto's playback pattern is `plu-{id}.m3u8`. Skip any channel with `license_url` (DRM). |
| **jmp2.uk** | Playback for Samsung and Pluto | Matt's redirect service; hands out a fresh signed stream link per tune. iptv-org uses it too. If it goes down, those channels die. Pluto links signed directly expire within about a day, which is why we don't sign them ourselves. |
| **iptv-org** (`github.com/iptv-org/iptv`) | Broadcasters' own streams, local stations, Tubi, Xumo, STIRR, Roku, Plex, Vizio, TCL and more | Read the raw source files (`raw.githubusercontent.com/iptv-org/iptv/master/streams/ca.m3u`), not the published `iptv-org.github.io/iptv/countries/*.m3u`. The published ones reformat names and drop call signs. Entries can carry `#EXTVLCOPT` user agents and referrers, which we pass through. Names carry tags like `(720p)`, `[Geo-blocked]`, `[Not 24/7]`. Per-service files exist (`us_roku`, `us_plex`, `au_samsung`, `uk_bbc` and dozens more). `tvg-id` is `Channel.cc@Feed` (`ABC.us@WMARTV`), which keys into the database. |
| **iptv-org database** (`github.com/iptv-org/database`, `data/*.csv`) | What each iptv-org channel is | `channels.csv` (categories, NSFW, closed date), `feeds.csv` (broadcast area like `ct/CAVAN` or `s/US-MD`, languages), `blocklist.csv` (legal and NSFW removals, always honoured), `cities.csv` and `subdivisions.csv` for place names. |
| **epgshare01** (`epgshare01.online/epgshare01/epg_ripper_*.xml.gz`) | Guides for broadcaster streams | `CA1` is gone (404); `CA2` works. Channel IDs are inconsistent: some by call sign (`CBXT-DT.ca2`), some by city (`CBC.Vancouver.HD.ca2`). Some entries go stale (listings ending days ago) while a sibling ID is current, so always match on upcoming listings. `US1` and `SAMSUNG1` are gone too; the US uses `US2`, `US_LOCALS1` (local stations, large) and `US_SPORTS1`. `UK1`, `AU1` and `NZ1` work. The publish report warns when a guide can't be fetched, so renames show up quickly. |
| **tv-logos** (`github.com/tv-logo/tv-logos`) | Clean transparent logos | Files named like `countries/canada/ctv-news-ca.png`. We list the repo tree once via the GitHub API and match by slugified channel name. |
| **TMDB** | Optional artwork | Works but no API key is set in CI yet. The owner questioned whether it's needed; source art is often fine. |
| **FastChannels** (`github.com/kineticman/FastChannels`) | Not used, but study it | The closest existing project: a big self-hosted aggregator with dozens of source integrations. Good reference for source APIs and quirks. The difference is that Open M3U is a hosted, curated, zero-setup list. |

### Lessons that cost time

- **CBC's local stations** (CBUT Vancouver and so on) were in iptv-org and looked fine, but they need a CBC Gem sign-in now and fail even in Canada. They were removed. The owner was asked to check whether **CBC News Network** and the **Ici Radio-Canada** stations play (same CBC servers); no answer yet.
- **Testing from the wrong country** was the biggest weakness: GitHub's runners are in the US, so region-limited streams elsewhere can't be verified. That's how the dead CBC stations slipped through. `openm3u verify` (section 3) is the fix, but it needs someone in each country.
- **Matt's Plex feed selects a region with a per-region forwarding header.** That works around Plex's regional restrictions, which this project doesn't do, so Plex streams come from iptv-org's direct links instead.
- **TiviMate appends episode numbers to the title** if the guide includes `<episode-num>` ("Arrow. S4 E8"). We don't output it; the episode goes at the start of the description instead.
- **Some feeds glue years or episodes onto titles** ("Heat (1995)", "The 100. S01E09"). `guide.tidy()` pulls them out.
- **Samsung's logos are square tiles.** They look boxy in a guide.
- **One-show channels are a huge share of FAST** (more than half of Pluto Canada). Newscasts look like one-show channels to a naive check, so live groups are exempt.
- **The UK BBC feed** lists every channel twice (normal and HEVC); HEVC copies are hidden.
- **TVNZ** is DRM-locked in Matt's feed.

---

## 5. Decisions and preferences (keep these unless the owner changes them)

### Product

- Free, publicly available streams only. No hosting or relaying video, no working around regional restrictions, no logins, no subscriptions, no DRM.
- Credit the sources on the site, keep a removal-request path (GitHub issues), and keep the "About these streams" disclaimer: not affiliated with any channel, names and logos belong to their owners, services' terms of use apply.
- Public wording: say "free, publicly available", not "legal". The project can't guarantee every service's terms allow third-party players, so it doesn't claim to.
- English first. Other languages go in their own block at the end (Canada: "En français", US: "En español"), never mixed in.
- Shopping, religious and adult channels are left out (the taxonomy's `[skip]` table). Free-to-air channels in Australia and New Zealand are carried whatever they are, because they're what a TV there gets.
- HD only: drop streams whose best quality is under 720p.
- One copy of each channel; the best working stream wins.

### Lineup

- Cable-style numbering: each group gets its own hundred (News 100s, Sports 200s, Movies 300s, Entertainment 400s, Comedy 500s, Reality 600s, Crime & Mystery 700s, Lifestyle & Documentary 800s, Kids 900s, Music 1000s, Series 1100s, other languages from 1400). Local stations go below 100. A group that outgrows its range continues 2000 higher (Entertainment 2400s).
- Fewer, bigger groups. The owner asked for this explicitly.
- "Real" channels first in every group: broadcasters and big networks (CBC, CTV, Global, ABC News, NFL...) before niche FAST channels.
- News runs national first, then city by city, west to east (Canada: Vancouver, Calgary, Edmonton, Saskatchewan, Manitoba, Toronto, Ottawa, Quebec, Atlantic, North).
- Australia and New Zealand keep the channel numbers locals know (Seven on 7x, Nine on 9x).
- Channels that loop a single show go to an alphabetized **Series** group rather than being dropped. The owner first said hide them, then changed his mind.
- Numbers stay stable between builds.
- MovieSphere (Samsung) and MovieSphere by Lionsgate (Pluto) are the same channel; keep the Lionsgate name.

### Guide

- The guide line shows only the show name. Episode number and title go at the start of the description ("S01E05 · The Good Son").
- Movies show their year: "Heat (1995)". If the year is unknown, show "(???)". The owner asked for this.
- Every channel should have real listings. Placeholders are a last resort.
- The playlist links its own guide (`x-tvg-url`), so most apps load it automatically.

### Site

- Warm palette, which the owner prefers over a white/black version he tried: paper `#f6f4ef`, card `#fffdf8`, ink `#1d1b18`, soft `#6f6a60`, rules `#e3ded3`, accent `#c2410c` (dark mode: paper `#141311`, ink `#ece8df`, accent `#fb923c`).
- Typeface Outfit (800 weight for the wordmark), JetBrains Mono for links and the build report.
- Clean and professional, with a slight technical, codey edge "because nerds will use it". It should feel like a product without feeling like a corporate product page.
- Structure the owner asked for: countries as rows, each with a copy-able playlist link and fold-outs for the lineup (category overview first, each category folding open to its channels), the guide link, and a build report. Setup instructions in a dropdown. A short "basic cable of IPTV" statement.

### Code and writing style

- The owner wants code that doesn't look AI-generated: no over-commenting, natural names, short docstrings only where they explain a non-obvious why.
- The owner doesn't want em dashes in any text written for him (site copy, docs, messages).
- Commit messages are plain, descriptive and human. Commits made by an AI should end with the attribution lines that tool requires.

---

## 6. Known issues and gaps

1. **In-country checks need someone in the country.** `openm3u verify ca` works today for Canada (the owner can run it). The UK, Australia and New Zealand need a friend, a small VPS or a self-hosted runner there.
2. **CBC News Network and Ici Radio-Canada** may need a Gem sign-in like the CBC locals. A Canadian `verify` run will answer this.
3. **No direct integrations for Tubi, Xumo, STIRR, LG, Vizio and friends.** They come in through iptv-org's per-service files, which are maintained and testable. Direct integrations couldn't be developed or tested from the sandbox (those hosts are unreachable), and iptv-org covers them.
4. **Plex via Matt's feed is deliberately not used:** it selects a region with a forwarding header, which works around regional restrictions. Plex channels come from iptv-org's direct streams; Matt's Plex guides are still used for listings.
5. **The US is big.** Offline it's 933 channels before epgshare guides; in CI it may reach well over 1,000. Groups overflow into the 2000s by design, but the owner may want to trim (for example, require HD 1080p for the long tail, or cap local stations).
6. **Australia only uses Sydney.** Matt publishes every capital city.
7. **Samsung's guide only runs about six hours ahead, Pluto's under a day.** Short guides are continued from any other guide carrying the same channel (Plex, Roku, epgshare), and whatever's still uncovered is filled with blocks named after the channel, so no slot in the 48-hour window reads "No information". The owner's standard is a perfect guide.
8. **TMDB isn't configured in CI.** Optional.
9. **The `v1.0.0` tag** needs creating on GitHub once the first CI build is green.

---

## 7. Owner's open questions

- **Merge Australia and New Zealand?** Still no: both countries' free-to-air channels only play in their own country.
- **Custom domain:** waiting on registration (section 9).

---

## 8. What could come next

1. Run `openm3u verify ca` from Canada and commit `checks/ca.json`.
2. Watch the first few CI builds' annotations and tune `hide` lists for the newly pulled iptv-org channels (`openm3u categories` helps spot unmapped labels).
3. Find in-country checkers for the UK, Australia and New Zealand.
4. Point openm3u.tv at Pages once registered.
5. Australian city variants, if wanted.

---

## 9. Rename checklist

- [x] Repo renamed to `jordanmarshall-dev/openm3u.tv`.
- [x] Package, CLI, imports, tests, workflows, `site.toml`, user agent, guide generator name, site copy.
- [x] Logo, favicon and social image from the owner's wordmark.
- [x] State carry-over: `previous_url` in `site.toml` points at the old Pages address, read once if the new site has no state yet. (If the old address is already gone, numbers start fresh once.)
- [x] README.
- [ ] Custom domain: once openm3u.tv is registered, point DNS at GitHub Pages (four `A` records for the apex: 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153), set the custom domain in the repo's Pages settings, and set `domain = "openm3u.tv"` in `site.toml`. That writes the `CNAME` file and switches every link to the domain.
