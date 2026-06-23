"""Output abstraction for interactive and non-interactive (quiet) modes.

In interactive mode (the default), output uses *rich* for styled progress bars,
spinners, and colour.  In quiet mode (``--quiet``), everything is plain text
suitable for cron jobs and log-file redirection.

Quiet-mode messages carry a ``[LEVEL]`` prefix so they remain grep-friendly
when redirected to a file::

    [INFO]  15 shelves
    [WARN]  Skipped abc123: rate-limited
    [ERROR] Cookie appears invalid
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from rich.console import Console
    from rich.progress import Progress as RichProgress

_quiet: bool = False
_console: Console | None = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init(quiet: bool = False) -> None:
    """Set the output mode.  Must be called once before any other function."""
    global _quiet, _console
    _quiet = quiet
    if not quiet:
        from rich.console import Console

        _console = Console()


def is_quiet() -> bool:
    return _quiet


# ---------------------------------------------------------------------------
# Low-level printing helpers
# ---------------------------------------------------------------------------

def log(msg: str, *, markup: bool = True) -> None:
    """Print a message.  *markup* controls rich markup in interactive mode."""
    if _quiet:
        print(msg, flush=True)
    else:
        assert _console is not None
        _console.print(msg, markup=markup)


def log_info(msg: str) -> None:
    if _quiet:
        print(f"[INFO]  {msg}", flush=True)
    else:
        assert _console is not None
        _console.print(f"\U0001f4dd  {msg}")  # 📝


def log_warn(msg: str) -> None:
    if _quiet:
        print(f"[WARN]  {msg}", flush=True)
    else:
        assert _console is not None
        _console.print(f"\U0001f7e1  {msg}")  # 🟡


def log_error(msg: str) -> None:
    if _quiet:
        print(f"[ERROR] {msg}", file=sys.stderr, flush=True)
    else:
        assert _console is not None
        _console.print(f"\u274c {msg}")  # ❌


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

@contextmanager
def status(msg: str) -> Iterator[None]:
    """Spinner in interactive mode; single log line then yield in quiet mode."""
    if _quiet:
        print(f"[INFO]  {msg}", flush=True)
        yield
    else:
        assert _console is not None
        with _console.status(msg):
            yield


class Progress:
    """Rich progress bar in interactive mode; simple counter in quiet mode.

    Usage::

        with Progress("Scraping books", total=N) as prog:
            for item in items:
                process(item)
                prog.advance()
    """

    def __init__(self, description: str, total: int) -> None:
        self._description = description
        self._total = total
        self._count: int = 0
        self._task = None
        self._progress: RichProgress | None = None

        if not _quiet:
            from rich.progress import (
                BarColumn,
                MofNCompleteColumn,
                Progress as RichProgress,
                SpinnerColumn,
                TaskProgressColumn,
                TextColumn,
                TimeElapsedColumn,
            )

            self._progress = RichProgress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=_console,
                transient=True,
            )

    # -- context-manager protocol -------------------------------------------

    def __enter__(self) -> Progress:
        if self._progress is not None:
            self._progress.__enter__()
            self._task = self._progress.add_task(
                self._description, total=self._total
            )
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: types.TracebackType | None) -> None:
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)

    # -- progress -----------------------------------------------------------

    def advance(self) -> None:
        self._count += 1
        if self._progress is not None:
            assert self._task is not None
            self._progress.advance(self._task)
