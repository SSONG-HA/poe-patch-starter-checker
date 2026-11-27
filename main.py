"""PoE-Patch-Starter-Checker 진입점.

인자 없이 실행하면 GUI, 인자가 있으면 CLI 로 동작한다.
"""
from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        from poe_checker.gui import launch

        return launch()
    from poe_checker.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
