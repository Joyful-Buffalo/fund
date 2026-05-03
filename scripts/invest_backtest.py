#!/usr/bin/env python3
"""Config-driven investing backtests for TQQQ and Nasdaq 100.

The engine is intentionally shared:
- asset differences live in AssetConfig;
- strategy differences live in one investment decision function.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable


DATA_DIR = Path("基金/纳指100")
TQQQ_SOURCE = DATA_DIR / "TQQQ ETF Stock Price History.csv"
NASDAQ_CSV_SOURCE = DATA_DIR / "SODHist_19850131-20260430_NDX.csv"

@dataclass(frozen=True)
class AssetConfig:
    key: str
    name: str
    source: Path
    date_column: str
    price_column: str
    date_format: str
    price_note: str
    source_note: str
    skip_nonpositive_prices: bool = False
    skip_weekends: bool = False


@dataclass(frozen=True)
class PriceRow:
    date: date
    close: float


@dataclass(frozen=True)
class InvestmentDecision:
    amount: float
    fields: dict[str, object]


@dataclass(frozen=True)
class StrategyConfig:
    key: str
    title: str
    file_label: str
    detail_fields: list[str]
    decision_fn: Callable[[PriceRow, PriceRow | None, argparse.Namespace], InvestmentDecision]


@dataclass(frozen=True)
class BacktestRow:
    date: date
    close: float
    daily_investment: float
    shares_bought: float
    cumulative_shares: float
    cumulative_cost: float
    market_value: float
    profit: float
    return_pct: float
    strategy_fields: dict[str, object]


@dataclass(frozen=True)
class OutputPaths:
    detail_csv: Path
    markdown: Path
    svg: Path


ASSETS: dict[str, AssetConfig] = {
    "tqqq": AssetConfig(
        key="tqqq",
        name="TQQQ",
        source=TQQQ_SOURCE,
        date_column="Date",
        price_column="Price",
        date_format="%m/%d/%Y",
        price_note="价格为拆分调整后的历史可比收盘价口径",
        source_note="数据源：本地 TQQQ 历史价格 CSV；不考虑汇率变化",
        skip_weekends=True,
    ),
    "nasdaq100": AssetConfig(
        key="nasdaq100",
        name="Nasdaq 100",
        source=NASDAQ_CSV_SOURCE,
        date_column="Trade Date",
        price_column="Index Value",
        date_format="%Y-%m-%d",
        price_note="价格为 Nasdaq 100 指数点位；剔除非正数的未完整收盘行",
        source_note="数据源：本地 Nasdaq 100 指数历史 CSV；不考虑汇率变化",
        skip_nonpositive_prices=True,
        skip_weekends=True,
    ),
}


def parse_iso_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"invalid ISO date: {value}") from exc


def clean_amount_for_name(amount: float) -> str:
    if amount.is_integer():
        return str(int(amount))
    return str(amount).replace(".", "_")


def clean_asset_for_name(asset_name: str) -> str:
    return "".join(char for char in asset_name if char.isalnum())


def fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def fmt_num(value: float, places: int = 4) -> str:
    return f"{value:,.{places}f}"


def fmt_pct(value: float) -> str:
    return f"{value * 100:,.2f}%"


def parse_date_value(value: str, date_format: str) -> date:
    return datetime.strptime(value, date_format).date()


def parse_price_value(value: str) -> float:
    return float(value.replace(",", "").strip())


def read_prices(
    source: Path,
    *,
    date_column: str,
    price_column: str,
    date_format: str,
    start_date: date | None,
    end_date: date | None,
    skip_nonpositive_prices: bool,
    skip_weekends: bool,
) -> list[PriceRow]:
    rows: list[PriceRow] = []
    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise SystemExit(f"empty CSV: {source}")
        missing = {date_column, price_column} - set(reader.fieldnames)
        if missing:
            raise SystemExit(f"{source} missing columns: {', '.join(sorted(missing))}")

        for raw in reader:
            if not raw.get(date_column) or not raw.get(price_column):
                continue
            row_date = parse_date_value(raw[date_column], date_format)
            if skip_weekends and row_date.weekday() >= 5:
                continue
            if start_date is not None and row_date < start_date:
                continue
            if end_date is not None and row_date > end_date:
                continue
            close = parse_price_value(raw[price_column])
            if close <= 0:
                if skip_nonpositive_prices:
                    continue
                raise SystemExit(f"non-positive close price on {row_date}: {close}")
            rows.append(PriceRow(row_date, close))

    rows.sort(key=lambda row: row.date)
    if not rows:
        raise SystemExit("no price rows after applying date filters")
    return rows


def fixed_daily_decision(price: PriceRow, previous: PriceRow | None, args: argparse.Namespace) -> InvestmentDecision:
    del price, previous
    if args.daily_amount <= 0:
        raise SystemExit("--daily-amount must be greater than 0")
    return InvestmentDecision(amount=args.daily_amount, fields={})


def buy_down_decision(price: PriceRow, previous: PriceRow | None, args: argparse.Namespace) -> InvestmentDecision:
    if args.base_amount <= 0:
        raise SystemExit("--base-amount must be greater than 0")
    if args.extra_per_percent < 0:
        raise SystemExit("--extra-per-percent must be greater than or equal to 0")

    change_pct = None if previous is None else price.close / previous.close - 1.0
    extra_amount = 0.0
    if change_pct is not None and change_pct < 0:
        extra_amount = -change_pct * 100.0 * args.extra_per_percent
    return InvestmentDecision(
        amount=args.base_amount + extra_amount,
        fields={
            "当日涨跌幅": None if change_pct is None else change_pct,
            "基础定投": args.base_amount,
            "额外加仓": extra_amount,
        },
    )


STRATEGIES: dict[str, StrategyConfig] = {
    "daily": StrategyConfig(
        key="daily",
        title="每日定投",
        file_label="每日定投",
        detail_fields=[],
        decision_fn=fixed_daily_decision,
    ),
    "buy_down": StrategyConfig(
        key="buy_down",
        title="方案二：下跌加仓",
        file_label="方案二_下跌加仓",
        detail_fields=["当日涨跌幅", "基础定投", "额外加仓"],
        decision_fn=buy_down_decision,
    ),
}


def calculate_backtest(prices: list[PriceRow], strategy: StrategyConfig, args: argparse.Namespace) -> list[BacktestRow]:
    cumulative_shares = 0.0
    cumulative_cost = 0.0
    previous: PriceRow | None = None
    rows: list[BacktestRow] = []

    for price in prices:
        decision = strategy.decision_fn(price, previous, args)
        if decision.amount <= 0:
            raise SystemExit(f"non-positive investment on {price.date}: {decision.amount}")

        shares_bought = decision.amount / price.close
        cumulative_shares += shares_bought
        cumulative_cost += decision.amount
        market_value = cumulative_shares * price.close
        profit = market_value - cumulative_cost
        rows.append(
            BacktestRow(
                date=price.date,
                close=price.close,
                daily_investment=decision.amount,
                shares_bought=shares_bought,
                cumulative_shares=cumulative_shares,
                cumulative_cost=cumulative_cost,
                market_value=market_value,
                profit=profit,
                return_pct=profit / cumulative_cost,
                strategy_fields=decision.fields,
            )
        )
        previous = price

    return rows


def yearly_snapshots(rows: list[BacktestRow]) -> list[dict[str, object]]:
    grouped: dict[int, list[BacktestRow]] = defaultdict(list)
    for row in rows:
        grouped[row.date.year].append(row)

    snapshots = []
    for year in sorted(grouped):
        year_rows = grouped[year]
        last = year_rows[-1]
        snapshots.append(
            {
                "year": year,
                "date": last.date,
                "year_invest": sum(row.daily_investment for row in year_rows),
                "cost": last.cumulative_cost,
                "close": last.close,
                "value": last.market_value,
                "profit": last.profit,
                "return_pct": last.return_pct,
            }
        )
    return snapshots


def format_strategy_field(value: object) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value * 100:.4f}%" if -1.0 < value < 1.0 else f"{value:.2f}"
    return str(value)


def write_detail_csv(path: Path, rows: list[BacktestRow], *, asset_name: str, strategy: StrategyConfig) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        fieldnames = [
            "日期",
            f"{asset_name}收盘价/点位",
            *strategy.detail_fields,
            "当日投入",
            "当日买入份额",
            "累计份额",
            "累计成本",
            "按当日收盘价/点位市值",
            "累计收益",
            "累计收益率",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            output = {
                "日期": row.date.isoformat(),
                f"{asset_name}收盘价/点位": f"{row.close:.4f}",
                "当日投入": f"{row.daily_investment:.2f}",
                "当日买入份额": f"{row.shares_bought:.8f}",
                "累计份额": f"{row.cumulative_shares:.8f}",
                "累计成本": f"{row.cumulative_cost:.2f}",
                "按当日收盘价/点位市值": f"{row.market_value:.2f}",
                "累计收益": f"{row.profit:.2f}",
                "累计收益率": f"{row.return_pct * 100:.4f}%",
            }
            for field in strategy.detail_fields:
                value = row.strategy_fields.get(field)
                if field in {"基础定投", "额外加仓"} and isinstance(value, (int, float)):
                    output[field] = f"{value:.2f}"
                else:
                    output[field] = format_strategy_field(value)
            writer.writerow(output)


def amount_axis(rows: list[BacktestRow]) -> tuple[float, float, list[float]]:
    values = []
    for row in rows:
        values.extend([row.cumulative_cost, row.market_value, row.profit])
    min_value = min(values)
    max_value = max(values)
    step = max(1.0, 10.0 ** max(0, math.floor(math.log10(max(abs(max_value), 1))) - 1))
    if max_value / step > 12:
        step *= 2.5
    ymin = -step if min_value < 0 else 0.0
    ymax = math.ceil(max_value / step) * step
    ticks = [ymin] if ymin < 0 else []
    current = 0.0
    while current <= ymax + step / 10:
        ticks.append(current)
        current += step
    return ymin, ymax, ticks


def return_axis(rows: list[BacktestRow]) -> tuple[float, float, list[float]]:
    values = [row.return_pct for row in rows]
    min_value = min(values)
    max_value = max(values)
    step = 0.5
    ymin = -step if min_value < 0 else 0.0
    ymax = max(step, math.ceil(max_value / step) * step)
    ticks = []
    current = ymin
    while current <= ymax + step / 10:
        ticks.append(current)
        current += step
    return ymin, ymax, ticks


def write_svg(
    path: Path,
    rows: list[BacktestRow],
    *,
    source_note: str,
    asset_name: str,
    title: str,
    subtitle: str,
) -> None:
    width, height = 1280, 760
    left, right, top, bottom = 92, 46, 86, 70
    gap = 42
    panel1_height = 400
    panel2_height = height - top - bottom - gap - panel1_height
    x0, x1 = left, width - right
    y1_top, y1_bottom = top, top + panel1_height
    y2_top, y2_bottom = y1_bottom + gap, height - bottom

    first = rows[0]
    last = rows[-1]
    min_ord = first.date.toordinal()
    max_ord = last.date.toordinal()
    ymin_amount, ymax_amount, amount_ticks = amount_axis(rows)
    ymin_return, ymax_return, return_ticks = return_axis(rows)

    def x_scale(row_date: date) -> float:
        if min_ord == max_ord:
            return (x0 + x1) / 2
        return x0 + (row_date.toordinal() - min_ord) / (max_ord - min_ord) * (x1 - x0)

    def y_amount(value: float) -> float:
        return y1_bottom - (value - ymin_amount) / (ymax_amount - ymin_amount) * (y1_bottom - y1_top)

    def y_return(value: float) -> float:
        return y2_bottom - (value - ymin_return) / (ymax_return - ymin_return) * (y2_bottom - y2_top)

    def path_for(key: str, y_scale) -> str:
        parts = []
        for index, row in enumerate(rows):
            value = getattr(row, key)
            parts.append(("M" if index == 0 else "L") + f"{x_scale(row.date):.2f},{y_scale(value):.2f}")
        return " ".join(parts)

    colors = {
        "cumulative_cost": "#1a73e8",
        "market_value": "#188038",
        "profit": "#d93025",
        "return_pct": "#9334e6",
    }
    labels = {
        "cumulative_cost": "累计成本",
        "market_value": "当前市值",
        "profit": "累计收益",
        "return_pct": "累计收益率",
    }

    svg: list[str] = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    svg.append("<style><![CDATA[")
    svg.append(
        "text{font-family:'Noto Sans CJK SC','Noto Sans CJK','Microsoft YaHei',Arial,sans-serif;fill:#202124}"
        " .axis{stroke:#5f6368;stroke-width:1} .grid{stroke:#dfe3e8;stroke-width:1}"
        " .small{font-size:14px;fill:#5f6368} .title{font-size:24px;font-weight:700}"
        " .subtitle{font-size:14px;fill:#5f6368} .label{font-size:15px} .legend{font-size:15px}"
    )
    svg.append("]]></style>")
    svg.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    svg.append(f'<text class="title" x="{left}" y="32">{html.escape(title)}</text>')
    svg.append(f'<text class="subtitle" x="{left}" y="54">{html.escape(subtitle)}</text>')
    svg.append(f'<text class="label" x="{left}" y="{y1_top - 14}">累计金额</text>')
    svg.append(f'<text class="label" x="{left}" y="{y2_top - 12}">累计收益率</text>')

    for tick in amount_ticks:
        y = y_amount(tick)
        label = f"{tick / 10000:.0f}万" if max(abs(t) for t in amount_ticks) >= 10000 else f"{tick:.0f}"
        svg.append(f'<line class="grid" x1="{x0}" y1="{y:.2f}" x2="{x1}" y2="{y:.2f}"/>')
        svg.append(f'<text class="small" x="{left - 10}" y="{y + 5:.2f}" text-anchor="end">{label}</text>')

    for tick in return_ticks:
        y = y_return(tick)
        svg.append(f'<line class="grid" x1="{x0}" y1="{y:.2f}" x2="{x1}" y2="{y:.2f}"/>')
        svg.append(f'<text class="small" x="{left - 10}" y="{y + 5:.2f}" text-anchor="end">{tick * 100:.0f}%</text>')

    for panel_top, panel_bottom in [(y1_top, y1_bottom), (y2_top, y2_bottom)]:
        svg.append(f'<line class="axis" x1="{x0}" y1="{panel_bottom}" x2="{x1}" y2="{panel_bottom}"/>')
        svg.append(f'<line class="axis" x1="{x0}" y1="{panel_top}" x2="{x0}" y2="{panel_bottom}"/>')

    for year in range(first.date.year, last.date.year + 1):
        year_start = date(year, 1, 1)
        if first.date <= year_start <= last.date:
            x = x_scale(year_start)
            svg.append(f'<line class="grid" x1="{x:.2f}" y1="{y1_top}" x2="{x:.2f}" y2="{y1_bottom}"/>')
            svg.append(f'<line class="grid" x1="{x:.2f}" y1="{y2_top}" x2="{x:.2f}" y2="{y2_bottom}"/>')
            svg.append(f'<text class="small" x="{x:.2f}" y="{height - 36}" text-anchor="middle">{year}</text>')
    svg.append(f'<text class="small" x="{x_scale(last.date):.2f}" y="{height - 36}" text-anchor="middle">{last.date.isoformat()}</text>')

    for key in ["cumulative_cost", "market_value", "profit"]:
        svg.append(
            f'<path d="{path_for(key, y_amount)}" fill="none" stroke="{colors[key]}" '
            'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    svg.append(
        f'<path d="{path_for("return_pct", y_return)}" fill="none" stroke="{colors["return_pct"]}" '
        'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    legend_x = width - 455
    legend_y = 27
    for index, key in enumerate(["cumulative_cost", "market_value", "profit", "return_pct"]):
        x = legend_x + index * 110
        svg.append(f'<line x1="{x}" y1="{legend_y}" x2="{x + 26}" y2="{legend_y}" stroke="{colors[key]}" stroke-width="4" stroke-linecap="round"/>')
        svg.append(f'<text class="legend" x="{x + 34}" y="{legend_y + 5}">{html.escape(labels[key])}</text>')

    latest = f"{asset_name}：市值 {last.market_value / 10000:.1f}万，收益 {last.profit / 10000:.1f}万，收益率 {last.return_pct * 100:.1f}%"
    svg.append(f'<circle cx="{x_scale(last.date):.2f}" cy="{y_amount(last.market_value):.2f}" r="4.5" fill="{colors["market_value"]}"/>')
    svg.append(f'<text class="small" x="{width - right}" y="{y1_top + 24}" text-anchor="end">{html.escape(latest)}</text>')
    svg.append(f'<text class="small" x="{width - right}" y="{height - 12}" text-anchor="end">{html.escape(source_note)}</text>')
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")


def strategy_summary_lines(rows: list[BacktestRow], strategy: StrategyConfig, args: argparse.Namespace) -> list[str]:
    if strategy.key == "daily":
        return [f"| 策略规则 | 每个交易日收盘投入 {args.daily_amount:g} 元，允许碎股 |"]

    extra_total = sum(float(row.strategy_fields.get("额外加仓", 0.0)) for row in rows)
    base_total = sum(float(row.strategy_fields.get("基础定投", 0.0)) for row in rows)
    down_days = sum(1 for row in rows if float(row.strategy_fields.get("额外加仓", 0.0)) > 0)
    max_extra = max(float(row.strategy_fields.get("额外加仓", 0.0)) for row in rows)
    max_daily = max(row.daily_investment for row in rows)
    return [
        f"| 策略规则 | 基础定投 {args.base_amount:g} 元；下跌时额外加仓 = 跌幅百分数 * {args.extra_per_percent:g} 元 |",
        f"| 下跌加仓天数 | {down_days:,} 天 |",
        f"| 基础定投合计 | {fmt_money(base_total)} |",
        f"| 额外加仓合计 | {fmt_money(extra_total)} |",
        f"| 最大单日额外加仓 | {fmt_money(max_extra)} |",
        f"| 最大单日投入 | {fmt_money(max_daily)} |",
    ]


def strategy_notes(strategy: StrategyConfig, args: argparse.Namespace, asset_name: str) -> list[str]:
    notes = [
        "- 不考虑汇率变化：投入金额、成本、市值和收益都按同一货币单位记录，不做美元/人民币转换。",
        f"- 不计入分红再投资、股息税、交易佣金、滑点和基金持有税费；仅按 {asset_name} 历史收盘价/点位模拟。",
        f"- 假设每个有 {asset_name} 收盘价/点位的交易日都能以收盘价/点位成交，并允许买入碎股。",
    ]
    if strategy.key == "buy_down":
        notes.extend(
            [
                "- 当日涨跌幅 = 当日收盘价/点位 / 上一交易日收盘价/点位 - 1；首个交易日没有上一交易日，只投入基础定投。",
                f"- 当日额外加仓 = max(0, -当日涨跌幅百分数) * {args.extra_per_percent:g}。例如下跌 1.23%，额外加仓 {1.23 * args.extra_per_percent:.2f} 元。",
                "- 上涨或持平时，额外加仓为 0，只投入基础定投。",
            ]
        )
    return notes


def formula_lines(strategy: StrategyConfig, args: argparse.Namespace) -> list[str]:
    if strategy.key == "daily":
        return [
            f"- 当日投入 = {args.daily_amount:g}",
            "- 当日买入份额 = 当日投入 / 当日收盘价或点位",
        ]
    return [
        "- 当日涨跌幅 = 当日收盘价或点位 / 上一交易日收盘价或点位 - 1",
        f"- 当日额外加仓 = max(0, -当日涨跌幅 * 100) * {args.extra_per_percent:g}",
        f"- 当日投入 = {args.base_amount:g} + 当日额外加仓",
        "- 当日买入份额 = 当日投入 / 当日收盘价或点位",
    ]


def write_markdown(
    path: Path,
    rows: list[BacktestRow],
    *,
    asset: AssetConfig,
    strategy: StrategyConfig,
    args: argparse.Namespace,
    source: Path,
    output_paths: OutputPaths,
    generated_on: date,
    requested_start_date: date | None,
) -> None:
    first = rows[0]
    last = rows[-1]
    snapshots = yearly_snapshots(rows)
    markdown: list[str] = []
    markdown.append(f"# {asset.name} {strategy.title}测算")
    markdown.append("")
    markdown.append(
        f"版本说明：本文件生成于 {generated_on.isoformat()}。当前可用的最新完整 {asset.name} 收盘数据为 "
        f"{last.date.isoformat()}，测算截止到 {last.date.isoformat()} 收盘。"
    )
    markdown.append("")
    markdown.append("## 1. 汇总表")
    markdown.append("")
    markdown.append("| 项目 | 数值 |")
    markdown.append("| --- | ---: |")
    markdown.extend(strategy_summary_lines(rows, strategy, args))
    if requested_start_date is not None and requested_start_date != first.date:
        markdown.append(f"| 请求开始日期 | {requested_start_date.isoformat()} |")
    markdown.append(f"| 实际开始日期 | {first.date.isoformat()} |")
    markdown.append(f"| 截止日期 | {last.date.isoformat()} 美股收盘 |")
    markdown.append(f"| 投入交易日数 | {len(rows):,} 天 |")
    markdown.append(f"| 累计成本 | {fmt_money(last.cumulative_cost)} |")
    markdown.append(f"| 累计份额 | {fmt_num(last.cumulative_shares)} |")
    markdown.append(f"| 最新收盘价/点位 | {fmt_money(last.close)} |")
    markdown.append(f"| 当前市值 | {fmt_money(last.market_value)} |")
    markdown.append(f"| 累计收益 | {fmt_money(last.profit)} |")
    markdown.append(f"| 累计收益率 | {fmt_pct(last.return_pct)} |")
    markdown.append("")
    markdown.append("## 2. 年度快照")
    markdown.append("")
    markdown.append("| 年份 | 截止日期 | 当年投入 | 累计成本 | 年末/当前收盘价 | 年末/当前市值 | 累计收益 | 累计收益率 |")
    markdown.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in snapshots:
        markdown.append(
            "| {year} | {date} | {year_invest} | {cost} | {close} | {value} | {profit} | {ret} |".format(
                year=row["year"],
                date=row["date"].isoformat(),
                year_invest=fmt_money(row["year_invest"]),
                cost=fmt_money(row["cost"]),
                close=fmt_money(row["close"]),
                value=fmt_money(row["value"]),
                profit=fmt_money(row["profit"]),
                ret=fmt_pct(row["return_pct"]),
            )
        )
    markdown.append("")
    markdown.append("## 3. 图像")
    markdown.append("")
    markdown.append(f"![{asset.name}{strategy.title}收益曲线]({output_paths.svg.name})")
    markdown.append("")
    markdown.append("## 4. 口径说明")
    markdown.append("")
    markdown.extend(strategy_notes(strategy, args, asset.name))
    markdown.append(f"- 历史价格使用本地 `{source.name}`，{asset.price_note}。")
    markdown.append(f"- 完整逐日明细见 `{output_paths.detail_csv.name}`，共 {len(rows):,} 行。")
    markdown.append("")
    markdown.append("## 5. 公式")
    markdown.append("")
    markdown.extend(formula_lines(strategy, args))
    markdown.append("- 累计份额 = 每日买入份额累计求和")
    markdown.append("- 累计成本 = 每日投入累计求和")
    markdown.append("- 当日市值 = 累计份额 * 当日收盘价或点位")
    markdown.append("- 累计收益 = 当日市值 - 累计成本")
    markdown.append("- 累计收益率 = 累计收益 / 累计成本")
    markdown.append("")
    markdown.append("## 6. 生成脚本")
    markdown.append("")
    markdown.append("- 脚本：`../../scripts/invest_backtest.py`")
    markdown.append(f"- 示例运行：`python scripts/invest_backtest.py run --asset {asset.key} --strategy {strategy.key}`")
    path.write_text("\n".join(markdown) + "\n", encoding="utf-8")


def build_output_paths(output_dir: Path, output_stem: str) -> OutputPaths:
    return OutputPaths(
        detail_csv=output_dir / f"{output_stem}.csv",
        markdown=output_dir / f"{output_stem}.md",
        svg=output_dir / f"{output_stem}.svg",
    )


def default_output_stem(
    *,
    asset: AssetConfig,
    strategy: StrategyConfig,
    args: argparse.Namespace,
    generated_on: date,
    label: str | None,
) -> str:
    asset_name = clean_asset_for_name(asset.name) or asset.key
    prefix = asset_name if label is None else f"{asset_name}_{label}"
    if strategy.key == "daily":
        amount_name = clean_amount_for_name(args.daily_amount)
        return f"{prefix}{strategy.file_label}{amount_name}_{generated_on:%Y_%m_%d}"
    return f"{prefix}{strategy.file_label}_{generated_on:%Y_%m_%d}"


def run_backtest(args: argparse.Namespace, *, label: str | None = None) -> OutputPaths:
    asset = ASSETS[args.asset]
    strategy = STRATEGIES[args.strategy]
    source = args.source or asset.source
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    generated_on = date.today()
    if start_date is not None and end_date is not None and start_date > end_date:
        raise SystemExit(f"start date {start_date.isoformat()} is after end date {end_date.isoformat()}")

    output_dir = args.output_dir or source.parent
    output_stem = args.output_stem or default_output_stem(asset=asset, strategy=strategy, args=args, generated_on=generated_on, label=label)
    output_paths = build_output_paths(output_dir, output_stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    prices = read_prices(
        source,
        date_column=asset.date_column,
        price_column=asset.price_column,
        date_format=asset.date_format,
        start_date=start_date,
        end_date=end_date,
        skip_nonpositive_prices=asset.skip_nonpositive_prices,
        skip_weekends=asset.skip_weekends,
    )
    rows = calculate_backtest(prices, strategy, args)

    if strategy.key == "daily":
        subtitle = (
            f"{rows[0].date.isoformat()} 至 {rows[-1].date.isoformat()}，"
            f"每日定投 {args.daily_amount:g} 元，不考虑汇率、分红和交易费"
        )
    else:
        subtitle = (
            f"{rows[0].date.isoformat()} 至 {rows[-1].date.isoformat()}，"
            f"基础定投 {args.base_amount:g} 元，下跌每 1% 额外加仓 {args.extra_per_percent:g} 元"
        )

    write_detail_csv(output_paths.detail_csv, rows, asset_name=asset.name, strategy=strategy)
    write_svg(
        output_paths.svg,
        rows,
        source_note=asset.source_note,
        asset_name=asset.name,
        title=f"{asset.name} {strategy.title}测算",
        subtitle=subtitle,
    )
    write_markdown(
        output_paths.markdown,
        rows,
        asset=asset,
        strategy=strategy,
        args=args,
        source=source,
        output_paths=output_paths,
        generated_on=generated_on,
        requested_start_date=start_date,
    )

    last = rows[-1]
    print(f"wrote: {output_paths.markdown}")
    print(f"wrote: {output_paths.detail_csv}")
    print(f"wrote: {output_paths.svg}")
    print(
        "summary: "
        f"asset={asset.name}, strategy={strategy.key}, days={len(rows):,}, "
        f"cost={last.cumulative_cost:.2f}, value={last.market_value:.2f}, "
        f"profit={last.profit:.2f}, return={last.return_pct * 100:.2f}%"
    )
    return output_paths


def table_start_date(asset: AssetConfig, *, source: Path | None = None) -> date:
    prices = read_prices(
        source or asset.source,
        date_column=asset.date_column,
        price_column=asset.price_column,
        date_format=asset.date_format,
        start_date=None,
        end_date=None,
        skip_nonpositive_prices=asset.skip_nonpositive_prices,
        skip_weekends=asset.skip_weekends,
    )
    return prices[0].date


def run_nasdaq_defaults(args: argparse.Namespace) -> None:
    asset = ASSETS["nasdaq100"]
    source = args.source or asset.source
    start_date = parse_iso_date(args.start_date) or table_start_date(asset, source=source)
    for strategy_key in ["daily", "buy_down"]:
        run_args = argparse.Namespace(
            asset="nasdaq100",
            strategy=strategy_key,
            source=source,
            daily_amount=args.daily_amount,
            base_amount=args.base_amount,
            extra_per_percent=args.extra_per_percent,
            output_dir=args.output_dir,
            output_stem=None,
            start_date=start_date.isoformat(),
            end_date=args.end_date,
        )
        run_backtest(run_args)


def add_common_backtest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", type=Path, default=None, help="override configured CSV source path")
    parser.add_argument("--daily-amount", type=float, default=50.0, help="fixed amount invested on each trading day")
    parser.add_argument("--base-amount", type=float, default=50.0, help="base amount invested on every trading day")
    parser.add_argument(
        "--extra-per-percent",
        type=float,
        default=100.0,
        help="extra amount for each 1 percentage point drop; 100 means -1.23%% adds 123",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="output directory; defaults to source parent")
    parser.add_argument("--output-stem", default=None, help="output filename without extension")
    parser.add_argument("--start-date", default=None, help="optional ISO date, e.g. 2010-02-11")
    parser.add_argument("--end-date", default=None, help="optional ISO date, e.g. 2026-04-29")
    parser.add_argument("--generated-on", default=None, help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run shared investing backtests for TQQQ and Nasdaq 100.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one asset/strategy backtest")
    run_parser.add_argument("--asset", choices=sorted(ASSETS), required=True)
    run_parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    add_common_backtest_args(run_parser)
    run_parser.set_defaults(func=run_backtest)

    nasdaq_parser = subparsers.add_parser("run-nasdaq-defaults", help="run Nasdaq 100 CSV through both strategies from one start date")
    nasdaq_parser.add_argument("--source", type=Path, default=None, help="Nasdaq 100 CSV source; defaults to configured source")
    nasdaq_parser.add_argument("--daily-amount", type=float, default=50.0)
    nasdaq_parser.add_argument("--base-amount", type=float, default=50.0)
    nasdaq_parser.add_argument("--extra-per-percent", type=float, default=100.0)
    nasdaq_parser.add_argument("--output-dir", type=Path, default=None)
    nasdaq_parser.add_argument("--start-date", default=None, help="optional ISO date; defaults to the table's earliest valid date")
    nasdaq_parser.add_argument("--end-date", default=None)
    nasdaq_parser.add_argument("--generated-on", default=None, help=argparse.SUPPRESS)
    nasdaq_parser.set_defaults(func=run_nasdaq_defaults)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
