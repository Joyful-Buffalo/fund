# -*- coding: utf-8 -*-
"""抓取 港股通央企红利指数（48） 的全收益历史曲线。"""
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
    "slug": "hk-connect-central-soe-dividend-48-total-return",
    "name": "港股通央企红利指数（48）",
    "code": "931722",
    "description_name": "港股通央企红利指数（48）全收益",
    "candidates": [
        [
            "csindex",
            "931722HKD210"
        ]
    ]
}


def main() -> None:
    run_one(INDEX_ITEM, wrapper_file=CURRENT_FILE)


if __name__ == "__main__":
    main()
