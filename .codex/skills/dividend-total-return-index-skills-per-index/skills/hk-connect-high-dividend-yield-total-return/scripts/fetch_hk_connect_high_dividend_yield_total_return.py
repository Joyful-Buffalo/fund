# -*- coding: utf-8 -*-
"""抓取 港股通高股息 的全收益历史曲线。"""
from __future__ import annotations

from pathlib import Path
import sys

CURRENT_FILE = Path(__file__).resolve()
SKILLS_ROOT = CURRENT_FILE.parents[2]
COMMON_SCRIPTS = SKILLS_ROOT / "dividend-total-return-common" / "scripts"

if str(COMMON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(COMMON_SCRIPTS))

from dividend_total_return_core import run_one

INDEX_ITEM = {
    "slug": "hk-connect-high-dividend-yield-total-return",
    "name": "港股通高股息",
    "code": "930914",
    "description_name": "港股通高股息全收益",
    "history_start_date": "2014-11-14",
    "candidates": [
        [
            "csindex",
            "H20914"
        ]
    ]
}


def main() -> None:
    run_one(INDEX_ITEM, wrapper_file=CURRENT_FILE)


if __name__ == "__main__":
    main()
