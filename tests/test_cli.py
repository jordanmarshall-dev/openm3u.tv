import json

import httpx

from openm3u import cli
from openm3u.checks import Checks

from .conftest import MIRRORS


def config(tmp_path, **extra):
    lines = [f'state_dir = "{tmp_path / "state"}"', f'checks_dir = "{tmp_path / "checks"}"']
    lines += [f'{key} = "{value}"' for key, value in extra.items()]
    lines.append("[mirrors]")
    lines += [f'"{k}" = "{v}"' for k, v in MIRRORS.items()]
    path = tmp_path / "openm3u.toml"
    path.write_text("\n".join(lines))
    return path


def test_verify_records_what_plays_from_here(tmp_path, monkeypatch):
    playlist = tmp_path / "ca.m3u"
    playlist.write_text(
        "#EXTM3U\n"
        "#EXTINF:-1,Good\nhttps://s.test/good/master.m3u8\n"
        "#EXTINF:-1,Gone\nhttps://s.test/gone/master.m3u8\n"
    )

    def handler(request):
        if "gone" in request.url.path:
            return httpx.Response(404)
        if request.url.path.endswith("master.m3u8"):
            return httpx.Response(200, text="#EXTM3U\n#EXTINF:6,\ns.ts\n")
        return httpx.Response(200, content=b"\x47" * 188)

    real = httpx.Client
    monkeypatch.setattr(
        cli.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    code = cli.main(["-c", str(config(tmp_path)), "verify", "ca", "--playlist", str(playlist)])
    assert code == 0
    checks = Checks.load(tmp_path / "checks" / "ca.json")
    assert checks.checked_from == "ca"
    good = checks.streams["https://s.test/good/master.m3u8"]
    gone = checks.streams["https://s.test/gone/master.m3u8"]
    assert (good.name, good.ok) == ("Good", True)
    assert (gone.ok, gone.label) == (False, "http 404")


def test_build_writes_a_playlist_offline(tmp_path, capsys):
    out = tmp_path / "out"
    path = config(tmp_path, output_dir=out, public_url="https://tv.example")
    assert cli.main(["-c", str(path), "build", "--skip-health", "--skip-tmdb"]) == 0
    text = (out / "ca.m3u").read_text()
    assert text.startswith('#EXTM3U x-tvg-url="https://tv.example/ca.xml.gz"')
    assert "Canada:" in capsys.readouterr().out


def test_publish_keeps_state_with_the_site(tmp_path):
    site = tmp_path / "site"
    path = config(tmp_path, public_url="https://tv.example")
    args = ["-c", str(path), "publish", "--site", str(site), "--skip-health", "--skip-tmdb"]
    assert cli.main(args) == 0
    state = json.loads((site / "state" / "ca.json").read_text())
    assert state["numbers"]


def test_categories_lists_unknown_labels(tmp_path, capsys):
    assert cli.main(["-c", str(config(tmp_path)), "categories"]) == 0
    assert "iptv-org" in capsys.readouterr().out
