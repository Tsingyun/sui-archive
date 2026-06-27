"""Text processing utilities for the SUI Archive build pipeline.

Provides helpers for truncating text (respecting Chinese sentence
boundaries and B站 emoji markers), escaping HTML, and normalizing
ISO 8601 timestamps used throughout the project.
"""

import html
import re
from datetime import datetime, timezone, timedelta

# Pre-compiled regex for B站 inline emoji markers such as [岁己收藏集表情包_晚安].
_EMOJI_BRACKET_RE = re.compile(r"\[[^\]]*\]")

# Sentence-ending punctuation (CJK + Latin).
_SENTENCE_ENDS = frozenset("。！？\n")

# Timezone offset for China Standard Time.
_CST = timezone(timedelta(hours=8))


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate *text* to at most *max_length* characters at a sentence
    boundary.

    Truncation rules (in priority order):

    1. If the full text fits within *max_length*, return it unchanged.
    2. Scan backwards from position *max_length* for the last sentence
       boundary (``。``, ``！``, ``？``, or ``\\n``).  Truncate there,
       *after* the punctuation.
    3. If no sentence boundary is found, truncate at a ``]`` that closes
       a B站 emoji marker (``[emoji_name]``) so that an emoji is never
       cut in the middle.
    4. As a last resort, hard-truncate at *max_length*.
    5. In all truncated cases, a trailing ``…`` is appended (and the
       total length including ``…`` stays within *max_length*).

    Parameters
    ----------
    text:
        The plain-text string to truncate.
    max_length:
        Maximum allowed length, including the ellipsis character.

    Returns
    -------
    str
        The (possibly truncated) text.
    """
    if text is None:
        return ""

    if len(text) <= max_length:
        return text

    # We need room for at least the ellipsis character.
    if max_length < 2:
        return text[:max_length]

    # The effective cut point leaves room for the trailing ellipsis.
    cut = max_length - 1  # -1 for '…'

    # Strategy 1: find the last sentence-ending punctuation within [0, cut].
    best = -1
    for i in range(cut, -1, -1):
        if text[i] in _SENTENCE_ENDS:
            best = i
            break

    if best >= 0:
        # Truncate right after the punctuation.
        truncated = text[: best + 1].rstrip()
        if truncated:
            return truncated + "…"

    # Strategy 2: avoid cutting inside an emoji bracket.
    # Find the last ']' before or at the cut point and check that the
    # corresponding '[' is also before the cut point.
    close_bracket = text.rfind("]", 0, cut + 1)
    if close_bracket >= 0:
        open_bracket = text.rfind("[", 0, close_bracket)
        if open_bracket >= 0:
            # The emoji marker is intact; cut after the ']'.
            truncated = text[: close_bracket + 1]
            if truncated:
                return truncated + "…"

    # Strategy 3: hard cut.
    return text[:cut] + "…"


def escape_html(text: str) -> str:
    """Escape HTML-sensitive characters in *text*.

    Converts ``<``, ``>``, ``&``, and ``"`` to their HTML entity
    equivalents so the string is safe for inclusion in HTML content or
    attribute values.

    Parameters
    ----------
    text:
        Raw text string.

    Returns
    -------
    str
        Escaped string safe for HTML output.
    """
    if text is None:
        return ""
    return html.escape(text, quote=True)


def format_iso8601(publish_time_str: str) -> str:
    """Normalize various timestamp formats to ``YYYY-MM-DDTHH:MM:SS+08:00``.

    Accepted input formats:

    * Unix timestamp as a string (e.g. ``"1654321000"``).
    * ISO 8601 with or without timezone offset.
    * Common date-time strings like ``"2024-03-15 14:30:00"``.
    * Date-only strings like ``"2024-03-15"`` (time defaults to 00:00:00).

    All outputs are converted to the ``+08:00`` (CST) timezone.

    Parameters
    ----------
    publish_time_str:
        The timestamp string to normalize.

    Returns
    -------
    str
        ISO 8601 formatted string with ``+08:00`` offset.

    Raises
    ------
    ValueError
        If the input cannot be parsed as any known format.
    """
    if publish_time_str is None:
        raise ValueError("publish_time_str must not be None")

    text = publish_time_str.strip()

    # 1. Pure digits → treat as Unix timestamp.
    if text.isdigit():
        ts = int(text)
        dt = datetime.fromtimestamp(ts, tz=_CST)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 2. Try ISO 8601 with timezone info.
    #    Python 3.7+ fromisoformat handles most variants.
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            # Assume CST when no timezone is given.
            dt = dt.replace(tzinfo=_CST)
        else:
            # Convert to CST.
            dt = dt.astimezone(_CST)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except (ValueError, TypeError):
        pass

    # 3. Common datetime format without separators.
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            dt = dt.replace(tzinfo=_CST)
            return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        except ValueError:
            continue

    raise ValueError(f"Unable to parse timestamp: {publish_time_str!r}")


def extract_year(iso_str: str) -> int:
    """Extract the year from an ISO 8601 string.

    Parameters
    ----------
    iso_str:
        An ISO 8601 timestamp (e.g. ``"2024-03-15T14:30:00+08:00"``).

    Returns
    -------
    int
        The four-digit year.
    """
    # The year is always the first four characters in ISO 8601.
    return int(iso_str[:4])


def extract_date(iso_str: str) -> str:
    """Extract the date portion from an ISO 8601 string.

    Parameters
    ----------
    iso_str:
        An ISO 8601 timestamp (e.g. ``"2024-03-15T14:30:00+08:00"``).

    Returns
    -------
    str
        Date string in ``YYYY-MM-DD`` format.
    """
    # The date is always the first ten characters in ISO 8601.
    return iso_str[:10]
