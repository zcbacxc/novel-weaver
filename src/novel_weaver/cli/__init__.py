"""CLI package."""

__all__ = ["main"]


def main(argv=None):
    from novel_weaver.cli.main import main as _main

    return _main(argv)
