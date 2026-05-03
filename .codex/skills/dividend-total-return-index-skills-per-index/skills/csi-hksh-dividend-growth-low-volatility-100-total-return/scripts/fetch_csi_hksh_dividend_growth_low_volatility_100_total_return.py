# -*- coding: utf-8 -*-
"""抓取 沪港深红利成长低波动指数（100） 的全收益历史曲线。"""
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
    "slug": "csi-hksh-dividend-growth-low-volatility-100-total-return",
    "name": "沪港深红利成长低波动指数（100）",
    "code": "931157",
    "description_name": "沪港深红利成长低波动指数（100）全收益",
    "candidates": [
        [
            "rising99",
            "H21157"
        ],
        [
            "csindex",
            "H21157"
        ]
    ]
}


def main() -> None:
    run_one(INDEX_ITEM, wrapper_file=CURRENT_FILE)


if __name__ == "__main__":
    main()
