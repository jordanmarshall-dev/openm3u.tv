from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
IPTV_ORG = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams"
DATABASE = "https://raw.githubusercontent.com/iptv-org/database/master/data"
MIRRORS = {
    "https://api.github.com/repos/tv-logo/tv-logos/git/trees/main?recursive=1": str(
        FIXTURES / "tv-logos-tree.json"
    ),
    "https://i.mjh.nz": str(FIXTURES / "mjh"),
    f"{IPTV_ORG}/ca.m3u": str(FIXTURES / "iptv-org-ca.m3u"),
    DATABASE: str(FIXTURES / "iptv-org-db"),
    "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz": str(FIXTURES / "epgshare-ca.xml"),
}


def hls_transport(pages: dict[str, tuple[int, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = pages.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)
