# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI package."""

__all__ = ["main"]


def main(argv=None):
    """Lazy-import and run the novel-weaver CLI entry point.

    Args:
        argv: Optional argument list; None uses sys.argv[1:].

    Returns:
        Process exit code from the CLI.
    """
    from novel_weaver.cli.main import main as _main

    return _main(argv)
