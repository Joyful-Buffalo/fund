# -*- coding: utf-8 -*-
"""
按每个红利指数的发布时间作为锚点，绘制红利指数全收益相对收益曲线。

口径：
- 每张图选择一个主指数，横轴从该主指数的发布时间开始。
- 每条指数曲线的收益起点为 max(主指数发布时间, 本指数发布时间)，不使用指数基准日归零。
- 在主指数发布时间已经发布的指数，在主指数发布时间之后首个可用日归零。
- 晚于主指数发布时间才发布或才有数据的指数，从自身发布时间之后首个可用日归零。
- 每张图按各曲线最后一个收益点降序排列，最后收益最高的排在图例前面。
- 图片按主指数发布时间升序输出，文件名前缀为序号和发布日期。
- 恒生红利低波动指数若没有官方历史日线，则使用本项目已有拟合曲线，并在输出中标注。
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent

DEFAULT_REFERENCE_MD = REPO_DIR / "fund" / "红利指数" / "earning.md"
DEFAULT_SKILL_DAILY_ROOT = REPO_DIR / "result" / "dividend_total_return_index_skills"
DEFAULT_EXCLUDED_NAMES = {"消费红利指数（50）"}
DEFAULT_DAILY_DIRS = [
    REPO_DIR / "result" / "index_return_curve" / "csv",
    REPO_DIR / "result" / "dividend_total_return_indices" / "csv",
]
HSI_INDEX_NAME = "恒生红利低波动指数（50）"
HSI_FIT_DAILY = (
    REPO_DIR
    / "result"
    / "hsi_hshylv_total_return_fit"
    / "csv"
    / "hshylv_fitted_total_return_daily.csv"
)
HSI_FIT_SUMMARY = (
    REPO_DIR
    / "result"
    / "hsi_hshylv_total_return_fit"
    / "csv"
    / "hshylv_fitted_total_return_summary.csv"
)

DEFAULT_OUT_DIR = REPO_DIR / "result" / "publish_relative_returns"


def set_chinese_font() -> None:
    candidates = [
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Noto Sans CJK TC",
        "Source Han Sans SC",
        "WenQuanYi Micro Hei",
        "SimHei",
        "Microsoft YaHei",
    ]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in candidates:
        if font_name in installed:
            plt.rcParams["font.sans-serif"] = [font_name]
            plt.rcParams["axes.unicode_minus"] = False
            print(f"[FONT] 使用中文字体: {font_name}")
            return
    print("[FONT] 未找到中文字体，图片中文可能显示为方框")


def normalize_name(name: object) -> str:
    return str(name).strip().replace("户港深", "沪港深")


def legacy_daily_filename(name: str) -> str:
    safe_name = re.sub(r'[\\/:*?"<>|（）()]', "_", name)
    return f"{safe_name}_daily.csv"


def output_safe_name(name: str) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z_\-.\u4e00-\u9fff]+", "_", name)
    return safe_name.strip("_")


def parse_date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def parse_markdown_table(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到发布时间表: {path}")

    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| ---") or "名称" in line:
            continue

        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue

        name = normalize_name(parts[0])
        base_date = parse_date(parts[1])
        publish_date = parse_date(parts[2])
        if publish_date is None:
            continue

        rows.append(
            {
                "name": name,
                "reference_base_date": base_date,
                "reference_publish_date": publish_date,
                "reference_weighting": parts[3] if len(parts) > 3 else None,
            }
        )

    if not rows:
        raise ValueError(f"未能从 {path} 解析到指数发布时间")
    return rows


def sort_by_publish_date(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for _, row in sorted(
            enumerate(rows),
            key=lambda item: (pd.Timestamp(item[1]["reference_publish_date"]), item[0]),
        )
    ]


def filter_reference_rows(rows: list[dict[str, object]], excluded_names: set[str]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if normalize_name(row["name"]) not in excluded_names
    ]


def pick_col(df: pd.DataFrame, candidates: list[str]) -> str:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in lower_map:
            return lower_map[key]
    raise KeyError(f"找不到列 {candidates}，实际列={list(df.columns)}")


def clean_daily(df: pd.DataFrame, name: str, source_path: Path, data_note: str) -> pd.DataFrame:
    date_col = pick_col(df, ["date", "日期", "tradeDate"])
    close_col = pick_col(df, ["close", "收盘", "收盘价", "fit_close", "price_close"])

    out = pd.DataFrame(
        {
            "name": name,
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "source_path": str(source_path.relative_to(REPO_DIR)),
            "data_note": data_note,
        }
    )
    out = out.dropna(subset=["date", "close"])
    out = out[out["close"] > 0]
    out["date"] = out["date"].dt.normalize()
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    return out.reset_index(drop=True)


def load_per_index_skill_daily_candidates(name: str, skill_daily_root: Path) -> list[pd.DataFrame]:
    if not skill_daily_root.exists():
        return []

    candidates = []
    for summary_path in sorted(skill_daily_root.glob("*/csv/*_summary.csv")):
        try:
            summary = pd.read_csv(summary_path)
        except pd.errors.EmptyDataError:
            continue

        if summary.empty or "name" not in summary.columns:
            continue
        if normalize_name(summary["name"].iloc[0]) != name:
            continue

        slug = summary_path.name.removesuffix("_summary.csv")
        daily_path = summary_path.with_name(f"{slug}_daily.csv")
        if not daily_path.exists():
            daily_files = sorted(summary_path.parent.glob("*_daily.csv"))
            if not daily_files:
                continue
            daily_path = daily_files[0]

        df = clean_daily(
            pd.read_csv(daily_path),
            name=name,
            source_path=daily_path,
            data_note="per_index_skill_total_return",
        )
        if len(df) >= 2:
            candidates.append(df)

    return candidates


def source_priority(df: pd.DataFrame) -> int:
    source_path = str(df["source_path"].iloc[0])
    if "dividend_total_return_index_skills" in source_path:
        return 1
    return 0


def load_standard_daily(name: str, daily_dirs: list[Path], skill_daily_root: Path) -> pd.DataFrame | None:
    candidates = load_per_index_skill_daily_candidates(name, skill_daily_root)
    filename = legacy_daily_filename(name)
    for daily_dir in daily_dirs:
        path = daily_dir / filename
        if not path.exists():
            continue

        df = clean_daily(
            pd.read_csv(path),
            name=name,
            source_path=path,
            data_note="official_or_project_total_return",
        )
        if len(df) >= 2:
            candidates.append(df)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda df: (
            pd.Timestamp(df["date"].max()),
            source_priority(df),
            len(df),
        ),
    )


def hsi_fit_note() -> str:
    if not HSI_FIT_SUMMARY.exists():
        return "fitted_total_return_not_official"

    try:
        summary = pd.read_csv(HSI_FIT_SUMMARY)
    except pd.errors.EmptyDataError:
        return "fitted_total_return_not_official"

    if summary.empty:
        return "fitted_total_return_not_official"

    note_parts = []
    for col in ["fit_warning", "fit_note"]:
        if col in summary.columns:
            value = summary[col].iloc[0]
            if pd.notna(value) and str(value).strip():
                note_parts.append(str(value).strip())
    return "；".join(note_parts) or "fitted_total_return_not_official"


def load_hsi_fit_daily() -> pd.DataFrame:
    if not HSI_FIT_DAILY.exists():
        raise FileNotFoundError(f"找不到恒生红利低波动拟合日线: {HSI_FIT_DAILY}")

    raw = pd.read_csv(HSI_FIT_DAILY)
    if "fit_close" not in raw.columns:
        raise KeyError(f"{HSI_FIT_DAILY} 缺少 fit_close 列")

    return clean_daily(
        raw[["date", "fit_close"]].rename(columns={"fit_close": "close"}),
        name=HSI_INDEX_NAME,
        source_path=HSI_FIT_DAILY,
        data_note=hsi_fit_note(),
    )


def load_all_series(
    reference_rows: list[dict[str, object]],
    daily_dirs: list[Path],
    skill_daily_root: Path,
) -> dict[str, pd.DataFrame]:
    series_map: dict[str, pd.DataFrame] = {}
    missing = []

    for row in reference_rows:
        name = str(row["name"])
        df = load_standard_daily(name, daily_dirs, skill_daily_root)

        if df is None and name == HSI_INDEX_NAME:
            df = load_hsi_fit_daily()

        if df is None:
            missing.append(name)
            continue

        series_map[name] = df

    if missing:
        raise FileNotFoundError("以下指数缺少可用日线: " + "、".join(missing))

    return series_map


def max_drawdown_pct(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    values = values[values > 0]
    if values.empty:
        return None
    drawdown = values / values.cummax() - 1
    return float((-drawdown.min()) * 100)


def annualized_return_pct(start_date: pd.Timestamp, end_date: pd.Timestamp, start_value: float, end_value: float) -> float | None:
    years = (end_date - start_date).days / 365.25
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return None
    return float(((end_value / start_value) ** (1 / years) - 1) * 100)


def build_relative_one(
    main_name: str,
    main_publish_date: pd.Timestamp,
    index_name: str,
    index_publish_date: pd.Timestamp,
    source_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object] | None]:
    df = source_df.sort_values("date").reset_index(drop=True)
    main_publish_date = pd.Timestamp(main_publish_date)
    index_publish_date = pd.Timestamp(index_publish_date)
    requested_return_start = max(main_publish_date, index_publish_date)
    after_start = df[df["date"] >= requested_return_start]

    if after_start.empty:
        return pd.DataFrame(), None

    base_row = after_start.iloc[0]
    if index_publish_date > main_publish_date:
        relation = "starts_at_index_publish"
    else:
        relation = "starts_at_main_publish"

    base_date = pd.Timestamp(base_row["date"])
    base_close = float(base_row["close"])
    if base_date > requested_return_start:
        relation = f"{relation}_next_available"

    plotted = df[df["date"] >= base_date].copy()
    if plotted.empty:
        return pd.DataFrame(), None

    plotted["main_name"] = main_name
    plotted["main_publish_date"] = main_publish_date
    plotted["index_publish_date"] = index_publish_date
    plotted["requested_return_start_date"] = requested_return_start
    plotted["visible_start_date"] = base_date
    plotted["base_date"] = base_date
    plotted["base_close"] = base_close
    plotted["relative_return"] = plotted["close"] / base_close - 1
    plotted["relative_return_pct"] = plotted["relative_return"] * 100
    plotted["return_start_relation"] = relation

    stats_window = df[df["date"] >= base_date].copy()
    if stats_window.empty:
        return pd.DataFrame(), None

    last_row = stats_window.iloc[-1]
    last_close = float(last_row["close"])
    summary = {
        "main_name": main_name,
        "main_publish_date": pd.Timestamp(main_publish_date).date().isoformat(),
        "name": index_name,
        "index_publish_date": index_publish_date.date().isoformat(),
        "requested_return_start_date": requested_return_start.date().isoformat(),
        "return_start_relation": relation,
        "data_start_date": df["date"].iloc[0].date().isoformat(),
        "base_date": base_date.date().isoformat(),
        "effective_return_start_date": base_date.date().isoformat(),
        "visible_start_date": base_date.date().isoformat(),
        "base_close": base_close,
        "last_date": pd.Timestamp(last_row["date"]).date().isoformat(),
        "last_close": last_close,
        "cum_return_pct": float((last_close / base_close - 1) * 100),
        "annualized_return_pct": annualized_return_pct(
            base_date,
            pd.Timestamp(last_row["date"]),
            base_close,
            last_close,
        ),
        "max_drawdown_pct": max_drawdown_pct(stats_window["close"]),
        "source_path": str(source_df["source_path"].iloc[0]),
        "data_note": str(source_df["data_note"].iloc[0]),
    }

    keep_cols = [
        "main_name",
        "main_publish_date",
        "name",
        "index_publish_date",
        "requested_return_start_date",
        "visible_start_date",
        "date",
        "close",
        "base_date",
        "base_close",
        "relative_return",
        "relative_return_pct",
        "return_start_relation",
        "source_path",
        "data_note",
    ]
    return plotted[keep_cols], summary


def build_relative_dataset(
    reference_rows: list[dict[str, object]],
    series_map: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_parts = []
    summary_rows = []

    for main in reference_rows:
        main_name = str(main["name"])
        main_publish_date = pd.Timestamp(main["reference_publish_date"])
        for row in reference_rows:
            index_name = str(row["name"])
            index_publish_date = pd.Timestamp(row["reference_publish_date"])
            relative_df, summary = build_relative_one(
                main_name=main_name,
                main_publish_date=main_publish_date,
                index_name=index_name,
                index_publish_date=index_publish_date,
                source_df=series_map[index_name],
            )
            if not relative_df.empty:
                long_parts.append(relative_df)
            if summary is not None:
                summary_rows.append(summary)

    long_df = pd.concat(long_parts, ignore_index=True) if long_parts else pd.DataFrame()
    summary_df = pd.DataFrame(summary_rows)
    return long_df, summary_df


def plot_for_main(
    main: dict[str, object],
    main_order: int,
    reference_rows: list[dict[str, object]],
    long_df: pd.DataFrame,
    png_dir: Path,
) -> Path:
    main_name = str(main["name"])
    anchor_date = pd.Timestamp(main["reference_publish_date"])
    data = long_df[long_df["main_name"] == main_name].copy()
    if data.empty:
        raise ValueError(f"{main_name} 没有可绘制数据")

    fig, ax = plt.subplots(figsize=(16, 9))
    cmap = plt.get_cmap("tab20")
    color_by_name = {
        str(row["name"]): cmap(idx % 20)
        for idx, row in enumerate(reference_rows)
    }
    final_returns = (
        data.sort_values("date")
        .groupby("name", as_index=False)
        .tail(1)
        .sort_values("relative_return_pct", ascending=False)
    )
    ordered_names = final_returns["name"].astype(str).tolist()

    for rank, name in enumerate(ordered_names, start=1):
        one = data[data["name"] == name]
        if one.empty:
            continue
        is_main = name == main_name
        ax.plot(
            one["date"],
            one["relative_return_pct"],
            label=f"{name}（主）" if is_main else name,
            color="#111111" if is_main else color_by_name.get(name, cmap(rank % 20)),
            linewidth=2.8 if is_main else 1.25,
            alpha=0.98 if is_main else 0.78,
            zorder=100 if is_main else len(ordered_names) - rank,
        )

    max_date = pd.to_datetime(data["date"]).max()
    ax.set_xlim(anchor_date, max_date)
    ax.axhline(0, color="#444444", linewidth=0.9, alpha=0.65)
    ax.grid(True, alpha=0.25)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_title(f"{main_name} 发布日起全收益相对收益", fontsize=18, pad=14)
    ax.set_xlabel("日期")
    ax.set_ylabel("累计收益率")

    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.13),
        ncol=3,
        fontsize=9,
        frameon=False,
    )

    fig.text(
        0.01,
        0.01,
        (
            f"图起点：{anchor_date.date().isoformat()}。每条曲线以 max(主指数发布时间, 本指数发布时间)"
            " 之后首个可用日归零；不使用指数基准日。"
        ),
        fontsize=9,
        color="#555555",
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0.08, 1, 1])

    date_prefix = anchor_date.date().isoformat()
    png_path = (
        png_dir
        / f"{main_order:02d}_{date_prefix}_{output_safe_name(main_name)}_发布日起全收益相对收益.png"
    )
    fig.savefig(png_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return png_path


def clean_generated_pngs(png_dir: Path) -> None:
    for path in png_dir.glob("*_发布日起全收益相对收益.png"):
        path.unlink()


def write_outputs(
    reference_rows: list[dict[str, object]],
    long_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    out_dir: Path,
) -> None:
    csv_dir = out_dir / "csv"
    png_dir = out_dir / "png"
    csv_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)
    clean_generated_pngs(png_dir)

    summary_path = csv_dir / "publish_relative_return_summary.csv"
    long_path = csv_dir / "publish_relative_return_long.csv"

    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    long_df.to_csv(long_path, index=False, encoding="utf-8-sig")

    png_paths = [
        plot_for_main(main, main_order, reference_rows, long_df, png_dir)
        for main_order, main in enumerate(reference_rows, start=1)
    ]

    print(f"[OK] 图片输出: {png_dir.resolve()} ({len(png_paths)} 张)")
    print(f"[OK] 统计输出: {summary_path.resolve()}")
    print(f"[OK] 明细输出: {long_path.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="绘制红利指数在各自主指数发布时间起的全收益相对收益曲线"
    )
    parser.add_argument(
        "--reference-md",
        type=Path,
        default=DEFAULT_REFERENCE_MD,
        help="包含指数基准日/发布时间的 Markdown 表格",
    )
    parser.add_argument(
        "--daily-dir",
        type=Path,
        action="append",
        default=None,
        help="旧版日线 CSV 目录，可重复传入；默认读取 result/index_return_curve/csv 和 result/dividend_total_return_indices/csv",
    )
    parser.add_argument(
        "--skill-daily-root",
        type=Path,
        default=DEFAULT_SKILL_DAILY_ROOT,
        help="单指数 skill 输出根目录；默认读取 result/dividend_total_return_index_skills",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="输出目录",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    daily_dirs = args.daily_dir or DEFAULT_DAILY_DIRS

    set_chinese_font()

    reference_rows = sort_by_publish_date(
        filter_reference_rows(parse_markdown_table(args.reference_md), DEFAULT_EXCLUDED_NAMES)
    )
    series_map = load_all_series(reference_rows, daily_dirs, args.skill_daily_root)
    long_df, summary_df = build_relative_dataset(reference_rows, series_map)
    write_outputs(reference_rows, long_df, summary_df, args.out_dir)


if __name__ == "__main__":
    main()
