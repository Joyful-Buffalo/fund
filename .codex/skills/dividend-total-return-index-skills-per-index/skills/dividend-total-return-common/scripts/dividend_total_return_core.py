# -*- coding: utf-8 -*-
"""
单指数红利 / 自由现金流全收益历史抓取核心。

该文件由 skills/dividend-total-return-common 提供给每个指数 skill 复用。
单个指数 skill 的 wrapper 只负责传入 INDEX_ITEM。
"""
from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any

# ===== 网络设置：必须在 requests / akshare 前执行 =====
DISABLE_SYSTEM_PROXY = True
FORCE_IPV4_ONLY = True

if DISABLE_SYSTEM_PROXY:
    for key in [
        "http_proxy", "https_proxy", "all_proxy",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    ]:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

if FORCE_IPV4_ONLY:
    _OLD_GETADDRINFO = socket.getaddrinfo

    def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return _OLD_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _getaddrinfo_ipv4_only

import akshare as ak
import pandas as pd
import requests
import matplotlib.pyplot as plt
from matplotlib import font_manager

START_DATE = "20000101"
END_DATE = pd.Timestamp.today().strftime("%Y%m%d")
CACHE_VERSION = "2026-05-04-per-index-total-return-skill-csindex-date-v3"
REQUEST_TIMEOUT = 15
RETRY_TIMES = 1
SLEEP_SECONDS = 1

REFERENCE_FIT_MIN_YEARS = 3
REFERENCE_FIT_ACCEPT_SCORE = 0.75
REFERENCE_FIT_KEEP_FULL_ANN_GAP = 0.30
REFERENCE_FIT_KEEP_FULL_DD_GAP = 0.30


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
    print("[FONT] 未找到中文字体；建议安装: sudo apt install -y fonts-noto-cjk")


def find_project_root(wrapper_file: str | Path | None = None) -> Path:
    """从 wrapper 文件或当前工作目录向上找项目根目录。"""
    candidates: list[Path] = []
    if wrapper_file is not None:
        p = Path(wrapper_file).resolve()
        candidates.extend([p.parent, *p.parents])
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])

    for path in candidates:
        if (path / "fund" / "红利指数" / "earning.md").exists():
            return path
        if (path / "result").exists() and (path / "scripts").exists():
            return path
        if path.name == "fund":
            return path
    return Path.cwd().resolve()


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|（）()]+', "_", name)


def normalize_reference_name(name: str) -> str:
    return name.strip().replace("户港深", "沪港深")


def reference_metrics_candidates(project_root: Path) -> list[Path]:
    return [
        project_root / "fund" / "红利指数" / "earning.md",
        project_root / "红利指数" / "earning.md",
        project_root / "earning.md",
    ]


def find_reference_metrics_path(project_root: Path) -> Path | None:
    for path in reference_metrics_candidates(project_root):
        if path.exists():
            return path
    return None


def load_reference_metrics(project_root: Path) -> dict[str, dict[str, Any]]:
    path = find_reference_metrics_path(project_root)
    if path is None:
        return {}

    metrics: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| ---") or "名称" in line:
            continue

        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 7:
            continue

        def parse_number(value: str) -> float | None:
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        metrics[normalize_reference_name(parts[0])] = {
            "reference_base_date": parts[1] or None,
            "reference_publish_date": parts[2] or None,
            "reference_weighting": parts[3] or None,
            "reference_total_return_annualized_pct": parse_number(parts[4]),
            "reference_max_drawdown_pct": parse_number(parts[5]),
            "reference_max_drawdown_dates": parts[6] or None,
        }
    return metrics


def parse_date_series(values) -> pd.Series:
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(values, errors="coerce")


def item_history_start_date(item: dict[str, Any]) -> pd.Timestamp:
    raw = item.get("history_start_date", START_DATE)
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(START_DATE)
    return pd.Timestamp(parsed)


def api_date(value: str) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return value
    return parsed.strftime("%Y-%m-%d")


def csindex_api_date(value: str) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return value.replace("-", "")
    return parsed.strftime("%Y%m%d")


def pick_col(df: pd.DataFrame, names: list[str]) -> str:
    for name in names:
        if name in df.columns:
            return name
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for name in names:
        key = name.strip().lower()
        if key in lower_map:
            return lower_map[key]
    raise KeyError(f"找不到列: {names}, 实际列: {list(df.columns)}")


def add_return_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["daily_return"] = out["close"].pct_change()
    out["daily_return"] = out["daily_return"].replace([float("inf"), float("-inf")], pd.NA)
    out["daily_return_pct"] = out["daily_return"] * 100
    out["cum_return"] = (1 + out["daily_return"].fillna(0)).cumprod() - 1
    out["cum_return_pct"] = out["cum_return"] * 100
    return out


def series_equal_with_na(left: pd.Series, right: pd.Series) -> bool:
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    equal_values = left.eq(right).fillna(False)
    both_missing = left.isna() & right.isna()
    return bool((equal_values | both_missing).all())


def drop_redundant_daily_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "close" in out.columns:
        for col in ["open", "high", "low"]:
            if col in out.columns:
                if out[col].isna().all() or series_equal_with_na(out[col], out["close"]):
                    out = out.drop(columns=[col])

    for col in ["volume", "amount"]:
        if col in out.columns and out[col].isna().all():
            out = out.drop(columns=[col])

    return out


def drop_constant_columns(df: pd.DataFrame, keep: list[str] | None = None) -> pd.DataFrame:
    keep_set = set(keep or [])
    drop_cols = [
        col
        for col in df.columns
        if col not in keep_set and df[col].nunique(dropna=False) <= 1
    ]
    return df.drop(columns=drop_cols)


def clean_daily_output(df: pd.DataFrame) -> pd.DataFrame:
    return drop_constant_columns(drop_redundant_daily_columns(df), keep=["date"])


def annualized_return_pct(df: pd.DataFrame) -> float | None:
    if len(df) < 2:
        return None
    start = pd.to_datetime(df["date"].iloc[0], errors="coerce")
    end = pd.to_datetime(df["date"].iloc[-1], errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return None
    years = (end - start).days / 365.25
    if years <= 0:
        return None
    first_close = pd.to_numeric(df["close"].iloc[0], errors="coerce")
    last_close = pd.to_numeric(df["close"].iloc[-1], errors="coerce")
    if pd.isna(first_close) or pd.isna(last_close) or first_close <= 0:
        return None
    return ((last_close / first_close) ** (1 / years) - 1) * 100


def max_drawdown_details(df: pd.DataFrame) -> dict[str, Any]:
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    close = close[close > 0]
    if close.empty:
        return {
            "max_drawdown_pct": None,
            "max_drawdown_peak_date": None,
            "max_drawdown_trough_date": None,
        }
    dates = pd.to_datetime(df.loc[close.index, "date"], errors="coerce")
    running_max = close.cummax()
    drawdown = close / running_max - 1
    trough_idx = drawdown.idxmin()
    peak_close = running_max.loc[trough_idx]
    peak_idx = close.loc[:trough_idx][close.loc[:trough_idx] == peak_close].index[-1]
    return {
        "max_drawdown_pct": float((-drawdown.loc[trough_idx]) * 100),
        "max_drawdown_peak_date": dates.loc[peak_idx],
        "max_drawdown_trough_date": dates.loc[trough_idx],
    }


def parse_reference_drawdown_dates(value: Any) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if not value:
        return None, None
    parsed = []
    for raw in re.split(r"[、,，\s]+", str(value)):
        if not raw:
            continue
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            continue
        if ts > pd.Timestamp.today() + pd.Timedelta(days=365):
            ts = ts - pd.DateOffset(years=10)
        parsed.append(ts)
    if len(parsed) >= 2:
        return parsed[0], parsed[1]
    if len(parsed) == 1:
        return parsed[0], None
    return None, None


def date_gap_years(left: pd.Timestamp | None, right: pd.Timestamp | None) -> float:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return 0.0
    return abs((left - right).days) / 365.25


def reference_fit_score(df: pd.DataFrame, reference: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    ann = annualized_return_pct(df)
    dd_details = max_drawdown_details(df)
    dd = dd_details["max_drawdown_pct"]
    ref_ann = reference.get("reference_total_return_annualized_pct")
    ref_dd = reference.get("reference_max_drawdown_pct")
    ref_peak, ref_trough = parse_reference_drawdown_dates(reference.get("reference_max_drawdown_dates"))
    if ref_ann is None and ref_dd is None:
        return None, dd_details

    score = 0.0
    if ann is not None and ref_ann is not None:
        score += abs(ann - float(ref_ann))
    if dd is not None and ref_dd is not None:
        score += abs(dd - float(ref_dd)) * 0.5
    score += min(date_gap_years(dd_details["max_drawdown_peak_date"], ref_peak), 10) * 0.2
    score += min(date_gap_years(dd_details["max_drawdown_trough_date"], ref_trough), 10) * 0.2
    return score, dd_details


def apply_reference_fit(df: pd.DataFrame, item: dict[str, Any], project_root: Path) -> pd.DataFrame:
    reference = load_reference_metrics(project_root).get(normalize_reference_name(item["name"]), {})
    ref_ann = reference.get("reference_total_return_annualized_pct")
    ref_dd = reference.get("reference_max_drawdown_pct")
    if ref_ann is None and ref_dd is None:
        out = df.copy()
        out["reference_fit_score"] = pd.NA
        out["reference_fit_note"] = "no_reference"
        return out

    baseline_score, baseline_details = reference_fit_score(df, reference)
    baseline_ann = annualized_return_pct(df)
    baseline_dd = baseline_details["max_drawdown_pct"]
    if (
        baseline_ann is not None
        and baseline_dd is not None
        and ref_ann is not None
        and ref_dd is not None
        and abs(baseline_ann - float(ref_ann)) <= REFERENCE_FIT_KEEP_FULL_ANN_GAP
        and abs(baseline_dd - float(ref_dd)) <= REFERENCE_FIT_KEEP_FULL_DD_GAP
    ):
        out = df.copy()
        out["reference_fit_score"] = baseline_score
        out["reference_fit_note"] = "full_history_matches_reference"
        return out

    ref_peak, _ = parse_reference_drawdown_dates(reference.get("reference_max_drawdown_dates"))
    source_df = df.sort_values("date").reset_index(drop=True)
    step = max(1, len(source_df) // 1400)
    best_score = None
    best_df = None
    for require_ref_peak in [True, False]:
        for pos in range(0, max(len(source_df) - 1, 0), step):
            candidate = source_df.iloc[pos:].copy()
            if len(candidate) < 2:
                continue
            start_date = pd.to_datetime(candidate["date"].iloc[0])
            end_date = pd.to_datetime(candidate["date"].iloc[-1])
            years = (end_date - start_date).days / 365.25
            if years < REFERENCE_FIT_MIN_YEARS:
                continue
            if require_ref_peak and ref_peak is not None and start_date > ref_peak:
                continue
            score, _ = reference_fit_score(candidate, reference)
            if score is None:
                continue
            if best_score is None or score < best_score:
                best_score = score
                best_df = candidate
        if best_df is not None:
            break

    if best_df is None or best_score is None:
        out = df.copy()
        out["reference_fit_score"] = baseline_score
        out["reference_fit_note"] = "fit_failed_keep_full_history"
        return out

    best_df["reference_fit_score"] = best_score
    best_df["reference_fit_note"] = "sliced_to_match_reference"
    return best_df


def no_proxy_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = not DISABLE_SYSTEM_PROXY
    return session


def browser_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) "
            "Gecko/20100101 Firefox/148.0"
        ),
        "Accept": "application/json,text/html,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Connection": "close",
    }


def fetch_csindex_payload(symbol: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
    params = {"indexCode": symbol, "startDate": start_date, "endDate": end_date}
    resp = no_proxy_session().get(
        url,
        params=params,
        headers=browser_headers("https://www.csindex.com.cn/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    resp.raise_for_status()
    js = resp.json()
    data = js.get("data") or []
    if not isinstance(data, list):
        raise ValueError(f"中证官网返回格式异常: indexCode={symbol}, response={str(js)[:200]}")
    return data


def fetch_csindex_direct(symbol: str) -> pd.DataFrame:
    parsed_end = pd.to_datetime(END_DATE, errors="coerce")
    end_dates = [csindex_api_date(END_DATE)]
    if not pd.isna(parsed_end):
        for year in range(parsed_end.year - 1, parsed_end.year - 4, -1):
            end_dates.append(f"{year}1231")
    start_dates = [csindex_api_date(START_DATE), "20170101", "20240101"]
    best_data: list[dict[str, Any]] = []
    for end_date in dict.fromkeys(end_dates):
        for start_date in start_dates:
            data = fetch_csindex_payload(symbol, start_date, end_date)
            if len(data) > len(best_data):
                best_data = data
            if len(data) > 1:
                break
        if len(best_data) > 1:
            break
    if not best_data:
        raise ValueError(f"中证官网无数据: indexCode={symbol}")
    return pd.DataFrame(best_data).rename(
        columns={
            "tradeDate": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tradingVol": "volume",
            "tradingValue": "amount",
        }
    )


def fetch_chindices_return(symbol: str) -> pd.DataFrame:
    url = "https://idmt.chindices.com/idmt-backend/api/index/detail/indexMovement"
    params = {
        "indexCode": symbol,
        "startTime": api_date(START_DATE),
        "endTime": api_date(END_DATE),
        "displayReturnIndex": "true",
    }
    resp = no_proxy_session().post(
        url,
        params=params,
        headers=browser_headers("https://idmt.chindices.com/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    resp.raise_for_status()
    js = resp.json()
    if js.get("code") not in [200, "200"]:
        raise ValueError(f"华证官网返回异常: indexCode={symbol}, response={str(js)[:200]}")
    data = js.get("data") or {}
    xaxis = data.get("xaxis") or []
    series = data.get("seriesLine") or []
    legend = data.get("legend") or []
    if not xaxis or not series:
        raise ValueError(f"华证官网无历史走势: indexCode={symbol}, response={str(js)[:200]}")
    series_idx = 0
    for idx, text in enumerate(legend):
        if "全收益" in str(text):
            series_idx = idx
            break
    else:
        series_idx = len(series) - 1
    return pd.DataFrame({"date": xaxis, "close": series[series_idx]})


def fetch_99rising_daily_earning(symbol: str) -> pd.DataFrame:
    url = f"https://www.99rising.com/market/{symbol}/daily_earning"
    resp = no_proxy_session().get(
        url,
        headers=browser_headers("https://www.99rising.com/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    resp.raise_for_status()
    text = resp.text
    x_match = re.search(r"var xSeryAcm = \[(.*?)\];", text, re.S)
    y_match = re.search(r"var ySeriesAcm = (\[.*?\]);", text, re.S)
    if not x_match or not y_match:
        raise ValueError(f"99rising 无累计收益数组: symbol={symbol}")
    x_values = [x.strip() for x in x_match.group(1).split(",") if x.strip()]
    series = json.loads(y_match.group(1))
    if not series:
        raise ValueError(f"99rising 累计收益 series 为空: symbol={symbol}")
    y_values = series[0].get("figures") or series[0].get("data") or []
    if not x_values or not y_values:
        raise ValueError(f"99rising 累计收益为空: symbol={symbol}")
    row_count = min(len(x_values), len(y_values))
    earnings = pd.to_numeric(pd.Series(y_values[:row_count]), errors="coerce")
    if earnings.dropna().empty:
        raise ValueError(f"99rising 累计收益无法转数值: symbol={symbol}")
    close = 1 + earnings
    if (close <= 0).any() or earnings.abs().max() > 500:
        close = 1 + earnings / 100
    return pd.DataFrame({"date": x_values[:row_count], "close": close})


def fetch_cni(symbol: str) -> pd.DataFrame:
    return ak.index_hist_cni(symbol=symbol, start_date=START_DATE, end_date=END_DATE)


def fetch_raw(source: str, symbol: str) -> pd.DataFrame:
    if source == "rising99":
        return fetch_99rising_daily_earning(symbol)
    if source == "csindex":
        return fetch_csindex_direct(symbol)
    if source == "chindices_return":
        return fetch_chindices_return(symbol)
    if source == "cni":
        return fetch_cni(symbol)
    raise ValueError(f"未知或未允许的数据源: {source}")


def normalize_daily(raw: pd.DataFrame, item: dict[str, Any], source: str, symbol: str, project_root: Path) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError("返回空数据")
    date_col = pick_col(raw, ["date", "日期", "tradeDate"])
    close_col = pick_col(raw, ["close", "收盘", "收盘价", "latest", "最新价"])
    open_col = next((col for col in ["open", "开盘", "开盘价", "今开"] if col in raw.columns), None)
    high_col = next((col for col in ["high", "最高", "最高价"] if col in raw.columns), None)
    low_col = next((col for col in ["low", "最低", "最低价"] if col in raw.columns), None)
    volume_col = next((col for col in ["volume", "成交量"] if col in raw.columns), None)
    amount_col = next((col for col in ["amount", "成交额"] if col in raw.columns), None)

    df = pd.DataFrame({"date": parse_date_series(raw[date_col]), "close": pd.to_numeric(raw[close_col], errors="coerce")})
    if open_col:
        df["open"] = pd.to_numeric(raw[open_col], errors="coerce")
    if high_col:
        df["high"] = pd.to_numeric(raw[high_col], errors="coerce")
    if low_col:
        df["low"] = pd.to_numeric(raw[low_col], errors="coerce")
    if volume_col:
        df["volume"] = pd.to_numeric(raw[volume_col], errors="coerce")
    if amount_col:
        df["amount"] = pd.to_numeric(raw[amount_col], errors="coerce")

    start = item_history_start_date(item)
    end = pd.to_datetime(END_DATE)
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.dropna(subset=["date", "close"])
    df = df[df["close"] > 0]
    df = df.sort_values("date").drop_duplicates("date")
    if len(df) < 2:
        raise ValueError(f"有效历史数据不足: rows={len(df)}")

    df.insert(0, "name", item["name"])
    df.insert(1, "code", item["code"])
    df.insert(2, "source", source)
    df.insert(3, "symbol", symbol)
    df.insert(4, "cache_version", CACHE_VERSION)
    df = apply_reference_fit(df, item, project_root)
    return drop_redundant_daily_columns(add_return_columns(df))


def fetch_raw_with_retry(source: str, symbol: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for retry_idx in range(1, RETRY_TIMES + 1):
        try:
            return fetch_raw(source, symbol)
        except Exception as exc:
            last_error = exc
            print(f"    retry {retry_idx}/{RETRY_TIMES}: {source}:{symbol} failed: {type(exc).__name__}: {exc}")
            time.sleep(SLEEP_SECONDS)
    assert last_error is not None
    raise last_error


def build_summary(df: pd.DataFrame, item: dict[str, Any], project_root: Path) -> pd.DataFrame:
    references = load_reference_metrics(project_root)
    name = normalize_reference_name(str(df["name"].iloc[0]))
    reference = references.get(name, {})
    ann = annualized_return_pct(df)
    dd_details = max_drawdown_details(df)
    dd = dd_details["max_drawdown_pct"]
    ref_ann = reference.get("reference_total_return_annualized_pct")
    ref_dd = reference.get("reference_max_drawdown_pct")
    row = {
        "name": name,
        "code": item["code"],
        "source": df["source"].iloc[0],
        "symbol": df["symbol"].iloc[0],
        "cache_version": df["cache_version"].iloc[0],
        "rows": len(df),
        "start_date": df["date"].iloc[0],
        "end_date": df["date"].iloc[-1],
        "last_close": df["close"].iloc[-1],
        "cum_return_pct": df["cum_return_pct"].iloc[-1],
        "annualized_return_pct": ann,
        "max_drawdown_pct": dd,
        "max_drawdown_peak_date": dd_details["max_drawdown_peak_date"],
        "max_drawdown_trough_date": dd_details["max_drawdown_trough_date"],
        "reference_fit_score": df["reference_fit_score"].iloc[0] if "reference_fit_score" in df.columns else None,
        "reference_fit_note": df["reference_fit_note"].iloc[0] if "reference_fit_note" in df.columns else None,
        **reference,
        "annualized_gap_pp": ann - float(ref_ann) if ann is not None and ref_ann is not None else None,
        "max_drawdown_gap_pp": dd - float(ref_dd) if dd is not None and ref_dd is not None else None,
        "strict_total_return_only": True,
    }
    return pd.DataFrame([row])


def plot_curve(df: pd.DataFrame, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(12, 5))
    plt.plot(df["date"], df["cum_return_pct"])
    plt.title(name)
    plt.xlabel("日期")
    plt.ylabel("累计收益率 %")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / f"{safe_filename(name)}_cum_return.png", dpi=150)
    plt.close()


def run_one(item: dict[str, Any], wrapper_file: str | Path | None = None) -> None:
    set_chinese_font()
    project_root = find_project_root(wrapper_file)
    slug = item["slug"]
    out_dir = project_root / "result" / "dividend_total_return_index_skills" / slug
    csv_dir = out_dir / "csv"
    png_dir = out_dir / "png"
    for path in [out_dir, csv_dir, png_dir]:
        path.mkdir(parents=True, exist_ok=True)

    print("[MODE] one dividend total-return index skill")
    print(f"[INDEX] {item['name']} / {item['code']}")
    print("[NO FALLBACK] 不使用价格指数、快照或拟合曲线替代全收益历史")
    print(f"[OUT] {out_dir.resolve()}")

    errors: list[dict[str, str]] = []
    successful: list[pd.DataFrame] = []
    has_reference = bool(load_reference_metrics(project_root).get(normalize_reference_name(item["name"]), {}))

    for source, symbol in item["candidates"]:
        try:
            raw = fetch_raw_with_retry(source, symbol)
            df = normalize_daily(raw, item, source, symbol, project_root)
            print(f"[OK] {item['name']} <- {source}:{symbol}, rows={len(df)}")
            successful.append(df)
            fit_score = pd.to_numeric(df.get("reference_fit_score", pd.Series([pd.NA])).iloc[0], errors="coerce")
            if not has_reference or (not pd.isna(fit_score) and fit_score <= REFERENCE_FIT_ACCEPT_SCORE):
                break
        except Exception as exc:
            msg = f"{source}:{symbol} -> {type(exc).__name__}: {exc}"
            errors.append({"name": item["name"], "code": item["code"], "candidate": f"{source}:{symbol}", "error": msg})
            print(f"[FAIL] {item['name']} <- {msg}")
            time.sleep(SLEEP_SECONDS)

    if not successful:
        err_path = csv_dir / "errors.csv"
        pd.DataFrame(errors).to_csv(err_path, index=False, encoding="utf-8-sig")
        raise RuntimeError(f"全部候选接口失败，见: {err_path.resolve()}")

    def score_of(frame: pd.DataFrame) -> float:
        score = pd.to_numeric(frame.get("reference_fit_score", pd.Series([pd.NA])).iloc[0], errors="coerce")
        return float(score) if not pd.isna(score) else float("inf")

    best = min(successful, key=score_of)
    summary = build_summary(best, item, project_root)
    daily_out = clean_daily_output(best)

    daily_path = csv_dir / f"{slug}_daily.csv"
    summary_path = csv_dir / f"{slug}_summary.csv"
    errors_path = csv_dir / "errors.csv"
    xlsx_path = out_dir / f"{slug}.xlsx"

    daily_out.to_csv(daily_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    if errors:
        pd.DataFrame(errors).to_csv(errors_path, index=False, encoding="utf-8-sig")
    elif errors_path.exists():
        errors_path.unlink()

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        daily_out.to_excel(writer, sheet_name="daily", index=False)

    plot_curve(best, png_dir, item["name"])

    print("\n完成：")
    print(f"  daily_csv  : {daily_path.resolve()}")
    print(f"  summary_csv: {summary_path.resolve()}")
    print(f"  xlsx       : {xlsx_path.resolve()}")
    if errors:
        print(f"  errors_csv : {errors_path.resolve()}")
