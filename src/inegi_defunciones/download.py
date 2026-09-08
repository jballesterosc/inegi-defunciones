"""HTTP download helpers: streaming, retries, resume, integrity checks."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests
from tqdm import tqdm

from .catalog import USER_AGENT

CHUNK = 1 << 20  # 1 MiB


class DownloadError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    return s


def download_file(
    url: str,
    dest: Path,
    *,
    force: bool = False,
    retries: int = 4,
    timeout: float = 60.0,
    session: requests.Session | None = None,
    quiet: bool = False,
) -> Path:
    """Download ``url`` to ``dest``, resuming a partial ``.part`` file if possible.

    Returns ``dest``. Skips the download when ``dest`` already exists unless
    ``force`` is set. Raises :class:`DownloadError` after exhausting ``retries``.
    """
    dest = Path(dest)
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    sess = session or _session()

    try:
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                _attempt_download(sess, url, part, timeout=timeout, quiet=quiet)
                part.replace(dest)
                return dest
            except (requests.RequestException, DownloadError) as exc:
                last_err = exc
                if attempt < retries:
                    wait = min(2**attempt, 30)
                    if not quiet:
                        tqdm.write(
                            f"  {dest.name}: {exc} — retrying in {wait}s "
                            f"({attempt}/{retries - 1})"
                        )
                    time.sleep(wait)
        raise DownloadError(f"failed to download {url}: {last_err}")
    finally:
        if session is None:
            sess.close()


def _attempt_download(
    sess: requests.Session, url: str, part: Path, *, timeout: float, quiet: bool
) -> None:
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}

    with sess.get(url, stream=True, headers=headers, timeout=timeout) as r:
        if have and r.status_code == 416:  # our .part is already the full file
            return
        if have and r.status_code == 200:  # server ignored Range -> start over
            have = 0
            part.unlink(missing_ok=True)
        r.raise_for_status()

        total = r.headers.get("Content-Length")
        total_bytes = int(total) + have if total is not None else None
        with (
            open(part, "ab" if have else "wb") as fh,
            tqdm(
                total=total_bytes,
                initial=have,
                unit="B",
                unit_scale=True,
                desc=part.stem,
                leave=False,
                disable=True if quiet else None,  # None => auto-off when not a TTY
            ) as bar,
        ):
            for chunk in r.iter_content(CHUNK):
                fh.write(chunk)
                bar.update(len(chunk))

    if total_bytes is not None and part.stat().st_size != total_bytes:
        raise DownloadError(
            f"size mismatch for {url}: got {part.stat().st_size}, expected {total_bytes}"
        )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
