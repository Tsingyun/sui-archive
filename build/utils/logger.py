"""Build logger for the SUI Archive build pipeline.

Provides :class:`BuildLogger`, a lightweight logger with colored ANSI
output and per-step timing.  Each build step calls ``step()`` to start a
new timed section and ``summary()`` at the end to print a build report
with total elapsed time.
"""

import sys
import time
from typing import Any


# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"

_COLORS = {
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "white":  "\033[37m",
    "gray":   "\033[90m",
}


def _supports_color() -> bool:
    """Return *True* if stdout appears to support ANSI escape codes."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


class BuildLogger:
    """Colored, timed build logger.

    Usage::

        log = BuildLogger()
        log.step("validate")
        log.info("Checking database integrity...")
        log.success("All checks passed.")

        log.step("json")
        log.info("Generating JSON files...")
        log.warn("40 images missing source_url.")
        log.success("Generated 5 JSON files.")

        log.summary({"steps": 2, "posts": 3547, "images": 1083})

    Parameters
    ----------
    verbose:
        When *True*, ``info()`` messages are printed.  When *False*,
        only warnings, errors, step headers, and the summary are shown.
    use_color:
        Force color on/off.  *None* (default) auto-detects from the
        terminal.
    """

    def __init__(
        self,
        verbose: bool = True,
        use_color: bool | None = None,
    ):
        self._verbose = verbose
        self._color = _supports_color() if use_color is None else use_color

        self._build_start: float = time.monotonic()
        self._step_start: float = self._build_start
        self._step_name: str | None = None
        self._step_timings: list[tuple[str, float]] = []

    # -- Internal helpers ---------------------------------------------------

    def _fmt(self, color: str, text: str) -> str:
        if self._color:
            return f"{_COLORS.get(color, '')}{text}{_RESET}"
        return text

    def _print(self, color: str, prefix: str, message: str) -> None:
        colored_prefix = self._fmt(color, f"[{prefix}]")
        print(f"{colored_prefix} {message}", flush=True)

    def _elapsed(self, seconds: float) -> str:
        """Format an elapsed duration as a human-readable string."""
        if seconds < 1.0:
            return f"{seconds * 1000:.0f}ms"
        if seconds < 60.0:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"

    # -- Public API ---------------------------------------------------------

    def step(self, name: str) -> None:
        """Start a new build step and print its header.

        If a previous step was active, its elapsed time is recorded for
        the final summary.
        """
        # Close the previous step (if any).
        if self._step_name is not None:
            elapsed = time.monotonic() - self._step_start
            self._step_timings.append((self._step_name, elapsed))

        self._step_name = name
        self._step_start = time.monotonic()

        line = self._fmt("cyan", f"\n{'='*60}")
        print(line, flush=True)
        header = self._fmt(_BOLD + _COLORS["cyan"], f"  STEP: {name}")
        print(header, flush=True)
        line = self._fmt("cyan", f"{'='*60}")
        print(line, flush=True)

    def info(self, msg: str) -> None:
        """Print an informational message (only when verbose is enabled)."""
        if self._verbose:
            self._print("white", "INFO", msg)

    def warn(self, msg: str) -> None:
        """Print a warning message (always shown)."""
        self._print("yellow", "WARN", msg)

    def error(self, msg: str) -> None:
        """Print an error message (always shown)."""
        self._print("red", "ERROR", msg)

    def success(self, msg: str) -> None:
        """Print a success message (always shown)."""
        self._print("green", " OK ", msg)

    def summary(self, stats: dict[str, Any] | None = None) -> None:
        """Print a build summary with per-step timings and optional stats.

        Parameters
        ----------
        stats:
            Optional dictionary of key-value pairs to include in the
            summary (e.g. ``{"posts": 3547, "images": 1083}``).
        """
        # Close the last step.
        if self._step_name is not None:
            elapsed = time.monotonic() - self._step_start
            self._step_timings.append((self._step_name, elapsed))
            self._step_name = None

        total_elapsed = time.monotonic() - self._build_start

        print("", flush=True)
        header = self._fmt("green", f"{'='*60}")
        print(header, flush=True)
        title = self._fmt(_BOLD + _COLORS["green"], "  BUILD SUMMARY")
        print(title, flush=True)
        header = self._fmt("green", f"{'='*60}")
        print(header, flush=True)

        # Per-step timings.
        if self._step_timings:
            print(self._fmt("gray", "  Step timings:"), flush=True)
            for name, secs in self._step_timings:
                t = self._fmt("gray", f"    {name:<20s} {self._elapsed(secs):>8s}")
                print(t, flush=True)

        # Extra stats.
        if stats:
            print(self._fmt("gray", "  Statistics:"), flush=True)
            for key, value in stats.items():
                if isinstance(value, int):
                    formatted = f"{value:,}"
                else:
                    formatted = str(value)
                s = self._fmt("gray", f"    {key:<20s} {formatted:>8s}")
                print(s, flush=True)

        # Total elapsed.
        total_str = self._fmt(
            _BOLD + _COLORS["green"],
            f"  Total elapsed: {self._elapsed(total_elapsed)}",
        )
        print("", flush=True)
        print(total_str, flush=True)
        print("", flush=True)
