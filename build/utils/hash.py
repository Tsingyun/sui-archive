"""Content hashing utilities for the SUI Archive build pipeline.

Provides functions to compute SHA-256 hashes for files and short content
hashes for CSS/JS cache busting.  The build system uses these to produce
fingerprinted asset filenames (e.g. ``style.a1b2c3d4.css``).
"""

import hashlib
from pathlib import Path

# Buffer size for streaming file hashing (64 KB).
_READ_CHUNK = 65536


def file_sha256(path: str | Path) -> str:
    """Return the hex-encoded SHA-256 digest of a file.

    The file is read in chunks to keep memory usage constant regardless
    of file size.

    Parameters
    ----------
    path:
        Filesystem path to the target file.

    Returns
    -------
    str
        64-character lowercase hex digest.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    IsADirectoryError
        If *path* is a directory.
    """
    path = Path(path)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def content_hash(content: str | bytes) -> str:
    """Return a short 8-character hash of *content* for cache busting.

    This is **not** cryptographically secure -- it is only used to
    fingerprint static assets (CSS, JS) so that browsers fetch a new
    file when its content changes.

    Parameters
    ----------
    content:
        The string or bytes to hash.  Strings are encoded as UTF-8
        before hashing.

    Returns
    -------
    str
        8-character lowercase hex digest (first 4 bytes of SHA-256).
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:8]
