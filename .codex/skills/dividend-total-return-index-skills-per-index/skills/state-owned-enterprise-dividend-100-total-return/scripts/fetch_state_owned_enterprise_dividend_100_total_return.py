# -*- coding: utf-8 -*-
"""抓取 国企红利指数（100） 的全收益历史曲线。"""
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
    "slug": "state-owned-enterprise-dividend-100-total-return",
    "name": "国企红利指数（100）",
    "code": "000824",
    "description_name": "国企红利指数（100）全收益",
    "candidates": [
        [
            "rising99",
            "H00824"
        ],
        [
            "csindex",
            "H00824"
        ]
    ]
}


def main() -> None:
    run_one(INDEX_ITEM, wrapper_file=CURRENT_FILE)


if __name__ == "__main__":
    main()
