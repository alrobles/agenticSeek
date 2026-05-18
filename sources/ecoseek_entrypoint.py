"""Console-script entry point for the ``ecoseek`` CLI.

This is a thin wrapper that:

* handles fast flags like ``--version`` without pulling in the heavy
  agent / browser / model imports;
* otherwise delegates to ``cli.main`` (the existing AgenticSeek async
  entry point that powers the historical ``agenticseek`` command).

Keeping this in its own module makes it cheap to import in tests and
packaging checks (``ecoseek --version`` works even when optional ML
dependencies are not installed).

Upstream AgenticSeek attribution is preserved — see ``NOTICE.md`` and
``UPSTREAM_CREDITS.md``.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence


__all__ = ["get_version", "main"]


def get_version() -> str:
    """Return the EcoSeek package version.

    Falls back to a hard-coded string when package metadata is
    unavailable (e.g. running from a source checkout that was never
    installed).
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - py<3.8
        return "0.1.0"
    for pkg in ("ecoseek", "agenticseek"):
        try:
            return version(pkg)
        except PackageNotFoundError:
            continue
    return "0.1.0"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Console-script entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("--version", "-V"):
        print(f"ecoseek {get_version()}")
        return 0

    if args and args[0] in ("--help", "-h"):
        print(
            "Usage: ecoseek [--version] [--help]\n"
            "\n"
            "Runs the EcoSeek interactive agent (forked from AgenticSeek).\n"
            "With no arguments, launches the interactive session defined\n"
            "in config.ini.\n"
        )
        return 0

    # Delegate to the existing async CLI. Import lazily so --version /
    # --help do not pay the cost of pulling in the agent stack.
    import asyncio

    from cli import main as cli_main  # type: ignore[import-not-found]

    asyncio.run(cli_main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
