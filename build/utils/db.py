"""SQLite connection manager for the SUI Archive build pipeline.

Provides a standardized way to connect to the project's SQLite database
with proper PRAGMAs (WAL mode, foreign keys, etc.) and context manager
support. All build steps that need database access should use
``get_connection()`` to obtain a correctly configured connection.
"""

import os
import sqlite3
from pathlib import Path

# Default database path relative to the project root.
_DEFAULT_DB_RELATIVE = "data/sui-archive.db"

# Marker file used to locate the project root directory.
_PROJECT_MARKER = "PROJECT_SPEC.md"


def get_project_root(start: str | Path | None = None) -> Path:
    """Walk up from *start* (defaults to this file's directory) and return
    the first ancestor that contains ``PROJECT_SPEC.md``.

    Raises ``FileNotFoundError`` if the marker cannot be found after
    reaching the filesystem root.
    """
    if start is None:
        # When running inside the real project tree, this file lives at
        # <root>/build/utils/db.py.  During development the caller may
        # pass an explicit *start* path.
        start = Path(__file__).resolve().parent

    current = Path(start).resolve()

    while True:
        if (current / _PROJECT_MARKER).is_file():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root without finding the marker.
            raise FileNotFoundError(
                f"Could not locate project root (looked for {_PROJECT_MARKER} "
                f"starting from {start})"
            )
        current = parent


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a new ``sqlite3.Connection`` configured for the SUI Archive
    database.

    The connection is set up with:

    * ``PRAGMA journal_mode = WAL``
    * ``PRAGMA foreign_keys = ON``
    * ``PRAGMA busy_timeout = 5000``
    * ``PRAGMA synchronous = NORMAL``
    * ``PRAGMA cache_size = -64000``  (64 MB)
    * ``PRAGMA temp_store = MEMORY``
    * ``row_factory = sqlite3.Row``

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  When *None* (the default),
        the path is resolved as ``<project_root>/data/sui-archive.db``.
        A relative path is interpreted relative to the project root.

    Returns
    -------
    sqlite3.Connection
        A ready-to-use database connection.  The caller is responsible
        for closing it (or using it as a context manager).
    """
    if db_path is None:
        root = get_project_root()
        db_path = root / _DEFAULT_DB_RELATIVE
    else:
        db_path = Path(db_path)
        if not db_path.is_absolute():
            root = get_project_root()
            db_path = root / db_path

    db_path = Path(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Apply the PRAGMAs mandated by DATABASE_SPEC.md (Appendix A).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")
    conn.execute("PRAGMA temp_store = MEMORY")

    return conn


class DatabaseContext:
    """Context manager that wraps a database connection.

    Usage::

        with DatabaseContext() as conn:
            rows = conn.execute("SELECT * FROM posts").fetchall()

    On normal exit the connection is committed and closed.  On
    exception the connection is rolled back and then closed.
    """

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = get_connection(self._db_path)
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is not None:
            try:
                if exc_type is None:
                    self._conn.commit()
                else:
                    self._conn.rollback()
            finally:
                self._conn.close()
                self._conn = None
