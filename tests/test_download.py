from __future__ import annotations

import http.server
import threading
from functools import partial

import pytest

from inegi_defunciones.download import DownloadError, download_file, sha256

PAYLOAD = b"defunciones-registradas" * 5000  # ~115 KB


@pytest.fixture()
def server(tmp_path):
    (tmp_path / "file.bin").write_bytes(PAYLOAD)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


def test_fresh_download(server, tmp_path):
    dest = tmp_path / "out" / "f.bin"
    download_file(f"{server}/file.bin", dest, quiet=True)
    assert dest.read_bytes() == PAYLOAD
    assert sha256(dest) == sha256(tmp_path / "file.bin")


def test_skips_when_present(server, tmp_path):
    dest = tmp_path / "f.bin"
    dest.write_bytes(b"already here")
    download_file(f"{server}/file.bin", dest, quiet=True)
    assert dest.read_bytes() == b"already here"  # untouched


def test_resume_from_partial(server, tmp_path):
    dest = tmp_path / "f.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(PAYLOAD[:1000])  # pretend a prior run stopped here
    download_file(f"{server}/file.bin", dest, quiet=True)
    assert dest.read_bytes() == PAYLOAD
    assert not part.exists()


def test_raises_on_bad_url(server, tmp_path):
    with pytest.raises(DownloadError):
        download_file(f"{server}/missing.bin", tmp_path / "x.bin", retries=2, quiet=True)
