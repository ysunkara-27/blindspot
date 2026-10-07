"""Fetch single members of a remote (uncompressed) tar with HTTP range requests, never storing the tar.

The MSD mirror (msd-for-monai S3) serves plain ustar archives with `Accept-Ranges: bytes`. Walking the 512-byte
headers costs one small request per member (~0.2 s); fetching a member is one ranged GET streamed to disk.
A whole-archive stream (`curl | tar`) would pull 7–12 GB per task to keep ~1 GB; this pulls only what we keep.

Index cache: <raw>/<Task>.index.json (resumable). Members: <raw>/<Task>/<path> written via .part + rename;
existing files with the indexed size are skipped. AppleDouble (`._*`) members are never fetched.
"""

from __future__ import annotations

import http.client
import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("volumetric.tar")

BLOCK = 512
CHUNK = 1 << 20


@dataclass(frozen=True)
class Member:
    name: str
    offset: int  # offset of the DATA (header is at offset - 512 for plain ustar entries)
    size: int
    typeflag: str

    @property
    def is_file(self) -> bool:
        return self.typeflag in ("0", "")

    @property
    def is_appledouble(self) -> bool:
        return Path(self.name).name.startswith("._")


class RangeClient:
    """A keep-alive HTTPS connection issuing ranged GETs with retries."""

    def __init__(self, url: str, *, timeout: float = 60.0, retries: int = 8):
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError(f"https only: {url}")
        self.host, self.path = parts.netloc, parts.path
        self.timeout, self.retries = timeout, retries
        self._conn: http.client.HTTPSConnection | None = None

    def _connect(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(self.host, timeout=self.timeout)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _request(self, start: int, end: int) -> http.client.HTTPResponse:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                conn = self._connect()
                conn.request("GET", self.path, headers={"Range": f"bytes={start}-{end}"})
                resp = conn.getresponse()
                if resp.status == 206:
                    return resp
                resp.read()
                raise OSError(f"HTTP {resp.status} for bytes={start}-{end}")
            except (OSError, http.client.HTTPException) as exc:  # includes socket timeouts
                last = exc
                self.close()
                time.sleep(min(2**attempt, 30))
        raise OSError(f"range request failed after {self.retries} attempts: {last}")

    def read(self, start: int, length: int) -> bytes:
        resp = self._request(start, start + length - 1)
        return resp.read()

    def total_size(self) -> int:
        resp = self._request(0, 0)
        resp.read()
        rng = resp.getheader("Content-Range") or ""
        return int(rng.rsplit("/", 1)[-1])

    def stream(self, start: int, length: int) -> Iterator[bytes]:
        resp = self._request(start, start + length - 1)
        got = 0
        while True:
            buf = resp.read(CHUNK)
            if not buf:
                break
            got += len(buf)
            yield buf
        if got != length:
            self.close()
            raise OSError(f"short read: {got} of {length} bytes")


# --------------------------------------------------------------------------- header parsing
def _field(h: bytes, start: int, size: int) -> str:
    return h[start : start + size].split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _octal(h: bytes, start: int, size: int) -> int:
    raw = h[start : start + size]
    if raw and raw[0] & 0x80:  # GNU base-256 size
        return int.from_bytes(raw[1:], "big")
    txt = raw.split(b"\0", 1)[0].strip()
    return int(txt, 8) if txt else 0


def parse_header(h: bytes) -> tuple[str, int, str] | None:
    """(name, size, typeflag) or None at the end-of-archive zero block."""
    if len(h) != BLOCK:
        raise ValueError(f"tar header must be {BLOCK} bytes, got {len(h)}")
    if h == b"\0" * BLOCK:
        return None
    name = _field(h, 0, 100)
    prefix = _field(h, 345, 155) if h[257:263] in (b"ustar\0", b"ustar ") else ""
    if prefix:
        name = f"{prefix}/{name}"
    return name, _octal(h, 124, 12), h[156:157].decode() or "0"


def walk(read: Callable[[int, int], bytes], *, total: int | None = None) -> Iterator[Member]:
    """Yield members by reading one header at a time. `read(offset, length)` returns bytes.

    Handles ustar prefix, GNU long names ('L') and pax headers ('x'/'g' are skipped — MSD names are short).
    """
    off = 0
    pending_long: str | None = None
    while total is None or off + BLOCK <= total:
        parsed = parse_header(read(off, BLOCK))
        if parsed is None:
            return
        name, size, typeflag = parsed
        data_off = off + BLOCK
        off = data_off + ((size + BLOCK - 1) // BLOCK) * BLOCK
        if typeflag == "L":
            pending_long = read(data_off, size).split(b"\0", 1)[0].decode()
            continue
        if typeflag in ("x", "g"):
            continue
        if pending_long is not None:
            name, pending_long = pending_long, None
        yield Member(name=name, offset=data_off, size=size, typeflag=typeflag)


def index_remote_tar(url: str, cache: Path | None = None, *, progress_every: int = 100) -> list[Member]:
    """Walk the remote tar's headers (one ranged GET each). Cached to `cache` as JSON."""
    if cache is not None and cache.exists():
        rows = json.loads(cache.read_text())
        if rows and rows[0].get("url") == url:
            return [Member(**{k: r[k] for k in ("name", "offset", "size", "typeflag")}) for r in rows]
    client = RangeClient(url)
    total = client.total_size()
    members: list[Member] = []
    t0 = time.time()
    try:
        for m in walk(client.read, total=total):
            members.append(m)
            if progress_every and len(members) % progress_every == 0:
                log.info(
                    "index %s: %d members, offset %.2f GB (%.0f s)", url, len(members), m.offset / 1e9, time.time() - t0
                )
    finally:
        client.close()
    log.info("index %s: %d members in %.0f s (archive %.2f GB)", url, len(members), time.time() - t0, total / 1e9)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([{**asdict(m), "url": url} for m in members]))
    return members


def fetch_member(url: str, member: Member, dest: Path, *, client: RangeClient | None = None) -> bool:
    """Download one member to `dest` (atomic via .part). Returns False when it was already there."""
    if dest.exists() and dest.stat().st_size == member.size:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or RangeClient(url)
    part = dest.with_suffix(dest.suffix + ".part")
    t0 = time.time()
    try:
        with part.open("wb") as fh:
            for buf in client.stream(member.offset, member.size):
                fh.write(buf)
        part.replace(dest)
    finally:
        if own:
            client.close()
    dt = max(time.time() - t0, 1e-6)
    log.info("fetched %s (%.1f MB, %.1f MB/s)", member.name, member.size / 1e6, member.size / 1e6 / dt)
    return True
