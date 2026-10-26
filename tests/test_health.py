import httpx

from openm3u.health import check, has_drm, parse_master, probe

from .conftest import hls_transport
from .factories import channel

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
hi/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
mid/index.m3u8
"""
MEDIA = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\nseg1.ts\n#EXTINF:6.0,\nseg2.ts\n"
BASE = "https://cdn.example/live/"


def client(pages):
    return httpx.Client(transport=hls_transport(pages))


def healthy_pages(master=MASTER, media=MEDIA):
    return {
        BASE + "master.m3u8": (200, master),
        BASE + "hi/index.m3u8": (200, media),
        BASE + "hi/seg1.ts": (200, "x" * 100),
    }


def test_parse_master_reads_quoted_attributes_and_resolves_urls():
    variants = parse_master(MASTER, BASE + "master.m3u8")
    assert [v.height for v in variants] == [360, 1080, 720]
    assert variants[1].bandwidth == 5_000_000
    assert variants[1].uri == BASE + "hi/index.m3u8"


def test_probe_reports_best_variant():
    report = probe(client(healthy_pages()), BASE + "master.m3u8")
    assert report.ok
    assert (report.height, report.bandwidth) == (1080, 5_000_000)
    assert report.label == "1080p"


def test_probe_flags_widevine():
    media = MEDIA.replace(
        "#EXTINF",
        '#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,KEYFORMAT="urn:uuid:'
        'edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n#EXTINF',
        1,
    )
    report = probe(client(healthy_pages(media=media)), BASE + "master.m3u8")
    assert not report.ok
    assert report.reason == "drm"


def test_plain_aes_is_not_drm():
    assert not has_drm('#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example/k"')


def test_probe_catches_dead_and_blocked_streams():
    assert probe(client({}), BASE + "master.m3u8").reason == "http 404"
    blocked = healthy_pages()
    blocked[BASE + "hi/seg1.ts"] = (403, "")
    assert probe(client(blocked), BASE + "master.m3u8").reason == "segment http 403"
    empty = healthy_pages(media="#EXTM3U\n#EXT-X-ENDLIST\n")
    assert probe(client(empty), BASE + "master.m3u8").reason == "no segments"


def test_check_retries_then_records_report():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    ch = channel("Flaky", url=BASE + "master.m3u8")
    check([ch], httpx.Client(transport=httpx.MockTransport(handler)), retries=1)
    assert len(calls) == 2
    assert ch.report.reason == "http 503"


def test_a_link_to_an_endless_video_stream_does_not_hang():
    def handler(request):
        def forever():
            while True:
                yield b"\x47" * 65536

        return httpx.Response(200, content=forever())

    report = probe(httpx.Client(transport=httpx.MockTransport(handler)), BASE + "master.m3u8")
    assert report.reason == "not a playlist"


def test_a_slow_drip_gives_up_at_the_deadline():
    import time as clock

    def handler(request):
        def drip():
            while True:
                clock.sleep(0.05)
                yield b"#"

        return httpx.Response(200, content=drip())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    started = clock.monotonic()
    assert probe(client, BASE + "master.m3u8", seconds=0.3).reason == "not a playlist"
    assert clock.monotonic() - started < 2
