# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI package."""

__all__ = ["main"]


def main(argv=None):
    from novel_weaver.cli.main import main as _main

    return _main(argv)
