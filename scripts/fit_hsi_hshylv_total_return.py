# -*- coding: utf-8 -*-
"""
恒生红利低波动指数 HSHYLV：拟合/估算全收益曲线 v2

修正点：
1. 不再把 2010-09-30 基准日起的官方参考年化，误认为已经有完整官方历史点位。
2. 明确标记：当前价格指数历史只从可获得日期开始，若晚于 2010-09-30，则为“截断区间拟合”。
3. 支持两种拟合：
   - annualized_only：只拟合目标年化，保留价格指数波动形状。
   - annualized_and_mdd：在拟合目标年化的基础上，用一个平滑修正项尽量校准最大回撤到参考值。

重要说明：
- 输出不是官方 HSHYLVDV / HSHYLVN 历史点位。
- 如果没有 2010-09-30 起的 HSHYLV 价格指数日线，就无法做严格基准日全区间拟合。
- annualized_and_mdd 属于工程校准曲线，比 annualized_only 更贴参考指标，但人为修正更强。
"""

import os
import re
import socket
import time
from pathlib import Path
from io import StringIO

import pandas as pd
import requests
import matplotlib.pyplot as plt
from matplotlib import font_manager


# =========================
# 网络配置
# =========================
DISABLE_SYSTEM_PROXY = True
FORCE_IPV4_ONLY = True
REQUEST_TIMEOUT = 20

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


# =========================
# 拟合参数
# =========================
INDEX_NAME = "恒生红利低波动指数（50）"
PRICE_CODE = "HSHYLV"
OFFICIAL_GROSS_TOTAL_RETURN_CODE = "HSHYLVDV"
OFFICIAL_NET_TOTAL_RETURN_CODE = "HSHYLVDVN/HSHYLVN"

REFERENCE_BASE_DATE = "2010-09-30"
REFERENCE_PUBLISH_DATE = "2017-05-08"
REFERENCE_WEIGHTING = "净股息率加权"
REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT = 8.20
REFERENCE_MAX_DRAWDOWN_PCT = 33.35
REFERENCE_MAX_DRAWDOWN_PEAK_DATE = "2021-09-13"
REFERENCE_MAX_DRAWDOWN_TROUGH_DATE = "2022-10-31"

# annualized_only：只拟合年化。
# annualized_and_mdd：拟合年化，并尽量把最大回撤校准到 REFERENCE_MAX_DRAWDOWN_PCT。
FIT_MODE = "annualized_and_mdd"

# 当前免费接口一般只能拿到 2019 年之后的 HSHYLV 价格指数历史。
# True：允许用可得价格区间做截断拟合，并在 summary 明确标注。
# False：如果价格日线不覆盖 2010-09-30，直接报错。
ALLOW_TRUNCATED_FIT = True

FIT_BASE_VALUE = 1000.0
START_DATE = "20000101"
END_DATE = pd.Timestamp.today().strftime("%Y%m%d")

# 优先读取上一个脚本已经输出的 HSHYLV 价格指数日线。
# 如果你手工下载了更长历史，把这个改成你的 CSV 路径，列名支持 date/日期 + close/收盘/price_close。
MANUAL_PRICE_CSV = ""
AUTO_PRICE_CSV_CANDIDATES = [
    "../result/hsi_hshylv_total_return_fit/csv/hshylv_price_daily.csv",
    "../result/index_return_curve/csv/恒生红利低波动指数_50__daily.csv",
]

# 回撤校准平滑形状宽度。越大，修正越平滑；越小，越集中在回撤谷底附近。
# 252 约等于一年交易日。当前 2019-2026 区间建议 180~320。
MDD_SHAPE_SIGMA_TRADING_DAYS = 252.0

# b 搜索范围。b 是对回撤谷底附近的指数型抬升/压低强度。
MDD_SHAPE_B_MIN = -2.0
MDD_SHAPE_B_MAX = 2.0
MDD_SHAPE_GRID_POINTS = 1601


# =========================
# 路径
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
OUT_DIR = REPO_DIR / "result" / "hsi_hshylv_total_return_fit"
CSV_DIR = OUT_DIR / "csv"
PNG_DIR = OUT_DIR / "png"
RAW_DIR = OUT_DIR / "raw"
for d in [OUT_DIR, CSV_DIR, PNG_DIR, RAW_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# =========================
# 基础工具
# =========================
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
    for name in candidates:
        if name in installed:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            print(f"[FONT] 使用中文字体: {name}")
            return
    print("[FONT] 未找到中文字体；建议安装: sudo apt install -y fonts-noto-cjk")


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


def safe_filename(text: str) -> str:
    return re.sub(r'[^0-9A-Za-z_\-.\u4e00-\u9fff]+', "_", text).strip("_")


def save_raw(name: str, content: str) -> None:
    path = RAW_DIR / f"{safe_filename(name)}.txt"
    path.write_text(content[:300_000], encoding="utf-8", errors="ignore")


def parse_date_series(values) -> pd.Series:
    series = pd.Series(values)
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() > 0.8 and not numeric.dropna().empty:
        max_value = numeric.dropna().max()
        if max_value > 1_000_000_000_000:
            return pd.to_datetime(numeric, errors="coerce", unit="ms")
        if max_value > 1_000_000_000:
            return pd.to_datetime(numeric, errors="coerce", unit="s")
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(series, errors="coerce")


def to_number_series(values) -> pd.Series:
    series = pd.Series(values).astype(str)
    series = series.str.replace(",", "", regex=False)
    series = series.str.replace("%", "", regex=False)
    series = series.str.replace("--", "", regex=False)
    series = series.str.strip()
    return pd.to_numeric(series, errors="coerce")


def series_equal_with_na(left: pd.Series, right: pd.Series) -> bool:
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    equal_values = left.eq(right).fillna(False)
    both_missing = left.isna() & right.isna()
    return bool((equal_values | both_missing).all())


def drop_redundant_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "price_close" in out.columns:
        for col in ["price_open", "price_high", "price_low"]:
            if col in out.columns:
                if out[col].isna().all() or series_equal_with_na(out[col], out["price_close"]):
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
    return drop_constant_columns(drop_redundant_price_columns(df), keep=["date"])


def pick_col(df: pd.DataFrame, names: list[str]) -> str:
    lower_to_original = {str(col).strip().lower(): col for col in df.columns}
    for name in names:
        key = name.strip().lower()
        if key in lower_to_original:
            return lower_to_original[key]
    raise KeyError(f"找不到列 {names}，实际列={list(df.columns)}")


def nearest_index_by_date(df: pd.DataFrame, date_str: str) -> int:
    target = pd.to_datetime(date_str)
    distances = (pd.to_datetime(df["date"]) - target).abs()
    return int(distances.idxmin())


def annualized_return_from_values(dates: pd.Series, values: pd.Series) -> float | None:
    if len(values) < 2:
        return None
    start = pd.to_datetime(dates.iloc[0], errors="coerce")
    end = pd.to_datetime(dates.iloc[-1], errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return None
    years = (end - start).days / 365.25
    if years <= 0:
        return None
    first_value = pd.to_numeric(values.iloc[0], errors="coerce")
    last_value = pd.to_numeric(values.iloc[-1], errors="coerce")
    if pd.isna(first_value) or pd.isna(last_value) or first_value <= 0:
        return None
    return ((last_value / first_value) ** (1 / years) - 1) * 100


def max_drawdown_details_from_values(dates: pd.Series, values: pd.Series) -> dict[str, object]:
    close = pd.to_numeric(values, errors="coerce")
    valid = close.notna() & (close > 0)
    close = close[valid]
    if close.empty:
        return {
            "max_drawdown_pct": None,
            "max_drawdown_peak_date": None,
            "max_drawdown_trough_date": None,
            "max_drawdown_peak_idx": None,
            "max_drawdown_trough_idx": None,
        }

    valid_dates = pd.to_datetime(dates.loc[close.index], errors="coerce")
    running_max = close.cummax()
    drawdown = close / running_max - 1
    trough_idx = drawdown.idxmin()
    peak_close = running_max.loc[trough_idx]
    peak_idx = close.loc[:trough_idx][close.loc[:trough_idx] == peak_close].index[-1]

    return {
        "max_drawdown_pct": float((-drawdown.loc[trough_idx]) * 100),
        "max_drawdown_peak_date": valid_dates.loc[peak_idx],
        "max_drawdown_trough_date": valid_dates.loc[trough_idx],
        "max_drawdown_peak_idx": int(peak_idx),
        "max_drawdown_trough_idx": int(trough_idx),
    }


# =========================
# 数据读取/抓取
# =========================
def normalize_price_daily(raw: pd.DataFrame, source: str, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError("返回空 DataFrame")

    date_col = pick_col(raw, ["date", "Date", "日期", "tradeDate", "timestamp", "time"])
    close_col = pick_col(raw, [
        "price_close", "close", "Close", "收盘", "收盘价", "最新价", "latest", "price", "Price",
    ])

    df = pd.DataFrame({
        "date": parse_date_series(raw[date_col]),
        "price_close": to_number_series(raw[close_col]),
    })

    optional_cols = {
        "price_open": ["price_open", "open", "Open", "开盘", "开盘价"],
        "price_high": ["price_high", "high", "High", "最高", "最高价"],
        "price_low": ["price_low", "low", "Low", "最低", "最低价"],
        "volume": ["volume", "Volume", "Vol.", "成交量"],
        "amount": ["amount", "Amount", "成交额"],
    }
    for output_col, candidates in optional_cols.items():
        try:
            raw_col = pick_col(raw, candidates)
            df[output_col] = to_number_series(raw[raw_col])
        except KeyError:
            pass

    start = pd.to_datetime(START_DATE, errors="coerce")
    end = pd.to_datetime(END_DATE, errors="coerce")
    if not pd.isna(start):
        df = df[df["date"] >= start]
    if not pd.isna(end):
        df = df[df["date"] <= end]

    df = df.dropna(subset=["date", "price_close"])
    df = df[df["price_close"] > 0]
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    if len(df) < 2:
        raise ValueError(f"有效价格历史不足: rows={len(df)}")

    df.insert(0, "index_name", INDEX_NAME)
    df.insert(1, "price_code", PRICE_CODE)
    df.insert(2, "price_source", source)
    df.insert(3, "price_symbol", symbol)
    df["price_daily_return"] = df["price_close"].pct_change()
    df["price_cum_return"] = (1 + df["price_daily_return"].fillna(0)).cumprod() - 1
    df["price_cum_return_pct"] = df["price_cum_return"] * 100
    return df


def read_csv_source(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return pd.read_csv(path)


def fetch_akshare_hk_index(symbol: str) -> pd.DataFrame:
    import akshare as ak
    return ak.stock_hk_index_daily_em(symbol=symbol)


def fetch_eastmoney_direct(secid: str) -> pd.DataFrame:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "0",
        "beg": START_DATE,
        "end": END_DATE,
    }
    resp = no_proxy_session().get(
        url,
        params=params,
        headers=browser_headers("https://quote.eastmoney.com/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    save_raw(f"eastmoney_{secid}", resp.text)
    resp.raise_for_status()
    js = resp.json()
    data = js.get("data")
    if not data or not data.get("klines"):
        raise ValueError(f"东方财富无数据: {str(js)[:300]}")

    rows = []
    for line in data["klines"]:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append({
            "date": parts[0],
            "open": parts[1],
            "close": parts[2],
            "high": parts[3],
            "low": parts[4],
            "volume": parts[5],
            "amount": parts[6] if len(parts) > 6 else None,
        })
    return pd.DataFrame(rows)


def fetch_yahoo_chart(symbol: str) -> pd.DataFrame:
    period2 = int(time.time())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "period1": 0,
        "period2": period2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    resp = no_proxy_session().get(
        url,
        params=params,
        headers=browser_headers("https://finance.yahoo.com/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    save_raw(f"yahoo_{symbol}", resp.text)
    resp.raise_for_status()
    js = resp.json()
    chart = js.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"Yahoo error: {chart.get('error')}")
    result_list = chart.get("result") or []
    if not result_list:
        raise ValueError("Yahoo 无 result")
    result = result_list[0]
    timestamps = result.get("timestamp") or []
    quote_list = (result.get("indicators") or {}).get("quote") or []
    if not timestamps or not quote_list:
        raise ValueError("Yahoo 无 timestamp/quote")
    quote = quote_list[0]
    close_values = quote.get("close") or []
    row_count = min(len(timestamps), len(close_values))
    if row_count <= 0:
        raise ValueError("Yahoo close 为空")
    return pd.DataFrame({
        "timestamp": timestamps[:row_count],
        "open": (quote.get("open") or [None] * row_count)[:row_count],
        "high": (quote.get("high") or [None] * row_count)[:row_count],
        "low": (quote.get("low") or [None] * row_count)[:row_count],
        "close": close_values[:row_count],
        "volume": (quote.get("volume") or [None] * row_count)[:row_count],
    })


def fetch_stooq_csv(symbol: str) -> pd.DataFrame:
    url = "https://stooq.com/q/d/l/"
    params = {"s": symbol, "i": "d", "d1": START_DATE, "d2": END_DATE}
    resp = no_proxy_session().get(
        url,
        params=params,
        headers=browser_headers("https://stooq.com/"),
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None} if DISABLE_SYSTEM_PROXY else None,
    )
    save_raw(f"stooq_{symbol}", resp.text)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No data" in text or len(text.splitlines()) <= 1:
        raise ValueError(f"Stooq 无数据: {text[:200]}")
    return pd.read_csv(StringIO(text))


def load_or_fetch_price_daily() -> tuple[pd.DataFrame, pd.DataFrame]:
    attempts: list[tuple[str, str, object]] = []
    errors = []

    def add(source: str, symbol: str, func):
        attempts.append((source, symbol, func))

    if MANUAL_PRICE_CSV.strip():
        manual_path = Path(MANUAL_PRICE_CSV).expanduser()
        if not manual_path.is_absolute():
            manual_path = (SCRIPT_DIR / manual_path).resolve()
        add("manual_csv", str(manual_path), lambda _s, p=manual_path: read_csv_source(p))

    for rel in AUTO_PRICE_CSV_CANDIDATES:
        path = (SCRIPT_DIR / rel).resolve()
        add("auto_csv", str(path), lambda _s, p=path: read_csv_source(p))

    add("akshare_hk_index", PRICE_CODE, fetch_akshare_hk_index)
    for secid in ["124.HSHYLV", "100.HSHYLV", "116.HSHYLV", "128.HSHYLV", "133.HSHYLV"]:
        add("eastmoney_direct", secid, fetch_eastmoney_direct)
    for symbol in ["HSHYLV", "^HSHYLV", "HSHYLV.HK", ".HSHYLV"]:
        add("yahoo_chart", symbol, fetch_yahoo_chart)
    for symbol in ["hshylv", "^hshylv", "hshylv.hk"]:
        add("stooq_csv", symbol, fetch_stooq_csv)

    for source, symbol, func in attempts:
        try:
            print(f"[TRY] price source={source}, symbol={symbol}")
            raw = func(symbol)
            df = normalize_price_daily(raw, source, symbol)
            print(
                f"[OK] price source={source}, symbol={symbol}, rows={len(df)}, "
                f"{df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()}"
            )
            return df, pd.DataFrame(errors)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            errors.append({"source": source, "symbol": symbol, "error": msg})
            print(f"[FAIL] price source={source}, symbol={symbol} -> {msg}")

    raise RuntimeError("所有 HSHYLV 价格指数数据源失败")


# =========================
# 拟合逻辑
# =========================
def build_mdd_shape(price_df: pd.DataFrame) -> pd.Series:
    n = len(price_df)
    positions = pd.Series(range(n), dtype="float64")

    ref_peak = pd.to_datetime(REFERENCE_MAX_DRAWDOWN_PEAK_DATE)
    ref_trough = pd.to_datetime(REFERENCE_MAX_DRAWDOWN_TROUGH_DATE)
    start = pd.to_datetime(price_df["date"].iloc[0])
    end = pd.to_datetime(price_df["date"].iloc[-1])

    if start <= ref_trough <= end:
        center_idx = nearest_index_by_date(price_df, REFERENCE_MAX_DRAWDOWN_TROUGH_DATE)
        shape_center_note = "reference_trough_date"
    else:
        price_dd = max_drawdown_details_from_values(price_df["date"], price_df["price_close"])
        center_idx = int(price_dd["max_drawdown_trough_idx"])
        shape_center_note = "price_actual_trough_date"

    sigma = float(MDD_SHAPE_SIGMA_TRADING_DAYS)
    gaussian = ((positions - center_idx) ** 2 / (-2.0 * sigma * sigma)).map(lambda x: pd.NA if pd.isna(x) else x)
    # 避免 pandas 对 exp 支持差异，转成 float 后使用 numpy。
    import numpy as np
    g = pd.Series(np.exp(gaussian.astype("float64")), index=price_df.index)

    # 两端压到 0，保证 b 不改变首尾点位，不影响最终年化。
    endpoint_line = pd.Series(
        [g.iloc[0] + (g.iloc[-1] - g.iloc[0]) * i / (n - 1) for i in range(n)],
        index=price_df.index,
        dtype="float64",
    )
    h = g - endpoint_line
    h = h - h.min()
    if h.max() > 0:
        h = h / h.max()

    # 再次确保首尾严格为 0。
    h.iloc[0] = 0.0
    h.iloc[-1] = 0.0
    price_df["mdd_shape_center_note"] = shape_center_note
    return h.astype("float64")


def make_curve(price_df: pd.DataFrame, daily_drift_factor: float, mdd_shape: pd.Series, b: float) -> pd.Series:
    import numpy as np
    n = len(price_df)
    positions = pd.Series(range(n), index=price_df.index, dtype="float64")
    price_norm = price_df["price_close"] / float(price_df["price_close"].iloc[0])
    drift = daily_drift_factor ** positions
    correction = pd.Series(np.exp(b * mdd_shape.astype("float64")), index=price_df.index)
    return FIT_BASE_VALUE * price_norm * drift * correction


def fit_curve(price_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = price_df.sort_values("date").reset_index(drop=True).copy()
    n = len(df)
    if n < 2:
        raise ValueError("价格指数历史不足，无法拟合")

    ref_base = pd.to_datetime(REFERENCE_BASE_DATE)
    start = pd.to_datetime(df["date"].iloc[0])
    end = pd.to_datetime(df["date"].iloc[-1])
    years = (end - start).days / 365.25
    if years <= 0:
        raise ValueError("日期跨度异常，无法计算年化")

    covers_reference_base = start <= ref_base
    if not covers_reference_base and not ALLOW_TRUNCATED_FIT:
        raise ValueError(
            f"价格指数起点 {start.date()} 晚于参考基准日 {ref_base.date()}，"
            "严格模式下不允许拟合。请提供覆盖基准日的 HSHYLV 价格日线 CSV。"
        )

    target_ann = REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT / 100.0
    target_growth = (1.0 + target_ann) ** years
    price_growth = float(df["price_close"].iloc[-1]) / float(df["price_close"].iloc[0])
    daily_drift_factor = (target_growth / price_growth) ** (1.0 / (n - 1))

    mdd_shape = build_mdd_shape(df)
    df["mdd_shape"] = mdd_shape

    # 先做只拟合年化的曲线。
    fit_b = 0.0
    fit_close = make_curve(df, daily_drift_factor, mdd_shape, fit_b)
    annualized_only_dd = max_drawdown_details_from_values(df["date"], fit_close)

    mdd_fit_status = "not_used"
    mdd_fit_abs_gap_pp = None
    if FIT_MODE == "annualized_and_mdd":
        import numpy as np
        best_b = 0.0
        best_gap = float("inf")
        best_close = fit_close
        best_dd = annualized_only_dd

        # 粗搜。
        for b in np.linspace(MDD_SHAPE_B_MIN, MDD_SHAPE_B_MAX, MDD_SHAPE_GRID_POINTS):
            candidate_close = make_curve(df, daily_drift_factor, mdd_shape, float(b))
            candidate_dd = max_drawdown_details_from_values(df["date"], candidate_close)
            dd_value = candidate_dd["max_drawdown_pct"]
            if dd_value is None:
                continue
            gap = abs(float(dd_value) - REFERENCE_MAX_DRAWDOWN_PCT)
            if gap < best_gap:
                best_gap = gap
                best_b = float(b)
                best_close = candidate_close
                best_dd = candidate_dd

        # 细搜。
        left = max(MDD_SHAPE_B_MIN, best_b - 0.02)
        right = min(MDD_SHAPE_B_MAX, best_b + 0.02)
        for b in np.linspace(left, right, 801):
            candidate_close = make_curve(df, daily_drift_factor, mdd_shape, float(b))
            candidate_dd = max_drawdown_details_from_values(df["date"], candidate_close)
            dd_value = candidate_dd["max_drawdown_pct"]
            if dd_value is None:
                continue
            gap = abs(float(dd_value) - REFERENCE_MAX_DRAWDOWN_PCT)
            if gap < best_gap:
                best_gap = gap
                best_b = float(b)
                best_close = candidate_close
                best_dd = candidate_dd

        fit_b = best_b
        fit_close = best_close
        mdd_fit_abs_gap_pp = best_gap
        mdd_fit_status = "calibrated" if best_gap <= 0.05 else "best_effort_not_exact"

    df["fit_close"] = fit_close
    df["fit_daily_return"] = df["fit_close"].pct_change()
    df["fit_cum_return"] = (1.0 + df["fit_daily_return"].fillna(0)).cumprod() - 1.0
    df["fit_cum_return_pct"] = df["fit_cum_return"] * 100.0
    df["fit_base_value"] = FIT_BASE_VALUE
    df["fit_mode"] = FIT_MODE
    df["daily_drift_factor"] = daily_drift_factor
    df["mdd_shape_b"] = fit_b
    df["target_total_return_annualized_pct"] = REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT
    df["target_max_drawdown_pct"] = REFERENCE_MAX_DRAWDOWN_PCT
    df["is_official_total_return_history"] = False
    df["is_truncated_range_fit"] = not covers_reference_base

    price_ann = annualized_return_from_values(df["date"], df["price_close"])
    fit_ann = annualized_return_from_values(df["date"], df["fit_close"])
    price_dd = max_drawdown_details_from_values(df["date"], df["price_close"])
    fit_dd = max_drawdown_details_from_values(df["date"], df["fit_close"])

    if not covers_reference_base:
        fit_warning = (
            f"价格指数可得起点 {start.date()} 晚于参考基准日 {ref_base.date()}；"
            "本结果是截断区间拟合，不是 2010-09-30 起完整拟合。"
        )
    else:
        fit_warning = "价格数据覆盖参考基准日，但仍然不是官方全收益历史点位。"

    summary = pd.DataFrame([{
        "index_name": INDEX_NAME,
        "price_code": PRICE_CODE,
        "official_gross_total_return_code": OFFICIAL_GROSS_TOTAL_RETURN_CODE,
        "official_net_total_return_code": OFFICIAL_NET_TOTAL_RETURN_CODE,
        "reference_base_date": REFERENCE_BASE_DATE,
        "reference_publish_date": REFERENCE_PUBLISH_DATE,
        "reference_weighting": REFERENCE_WEIGHTING,
        "reference_total_return_annualized_pct": REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT,
        "reference_max_drawdown_pct": REFERENCE_MAX_DRAWDOWN_PCT,
        "reference_max_drawdown_dates": f"{REFERENCE_MAX_DRAWDOWN_PEAK_DATE}、{REFERENCE_MAX_DRAWDOWN_TROUGH_DATE}",
        "fit_mode": FIT_MODE,
        "is_official_total_return_history": False,
        "is_truncated_range_fit": not covers_reference_base,
        "price_data_covers_reference_base": covers_reference_base,
        "price_source": df["price_source"].iloc[0],
        "price_symbol": df["price_symbol"].iloc[0],
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "rows": n,
        "years": years,
        "price_first_close": float(df["price_close"].iloc[0]),
        "price_last_close": float(df["price_close"].iloc[-1]),
        "price_annualized_return_pct": price_ann,
        "fit_annualized_return_pct": fit_ann,
        "fit_annualized_gap_pp": None if fit_ann is None else fit_ann - REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT,
        "price_max_drawdown_pct": price_dd["max_drawdown_pct"],
        "price_max_drawdown_peak_date": price_dd["max_drawdown_peak_date"],
        "price_max_drawdown_trough_date": price_dd["max_drawdown_trough_date"],
        "annualized_only_fit_max_drawdown_pct": annualized_only_dd["max_drawdown_pct"],
        "fit_max_drawdown_pct": fit_dd["max_drawdown_pct"],
        "fit_max_drawdown_peak_date": fit_dd["max_drawdown_peak_date"],
        "fit_max_drawdown_trough_date": fit_dd["max_drawdown_trough_date"],
        "fit_max_drawdown_gap_pp": None if fit_dd["max_drawdown_pct"] is None else fit_dd["max_drawdown_pct"] - REFERENCE_MAX_DRAWDOWN_PCT,
        "mdd_fit_status": mdd_fit_status,
        "mdd_fit_abs_gap_pp": mdd_fit_abs_gap_pp,
        "daily_drift_factor": daily_drift_factor,
        "mdd_shape_b": fit_b,
        "mdd_shape_sigma_trading_days": MDD_SHAPE_SIGMA_TRADING_DAYS,
        "mdd_shape_center_note": df["mdd_shape_center_note"].iloc[0] if "mdd_shape_center_note" in df.columns else None,
        "fit_warning": fit_warning,
        "fit_note": (
            "拟合估算曲线，不是官方 HSHYLVDV/HSHYLVN 历史点位。"
            "若要严谨对比，应取得官方全收益历史日线或覆盖基准日的价格日线。"
        ),
    }])

    return df, summary


# =========================
# 输出
# =========================
def plot_outputs(df: pd.DataFrame) -> None:
    plt.figure(figsize=(12, 5))
    plt.plot(df["date"], df["price_cum_return_pct"], label="HSHYLV 价格指数累计收益")
    plt.plot(df["date"], df["fit_cum_return_pct"], label=f"拟合全收益累计收益：{FIT_MODE}")
    plt.title("恒生红利低波动指数：价格指数 vs 拟合全收益曲线")
    plt.xlabel("日期")
    plt.ylabel("累计收益率 %")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PNG_DIR / "hshylv_price_vs_fitted_total_return.png", dpi=150)
    plt.close()

    plt.figure(figsize=(12, 4))
    plt.plot(df["date"], df["mdd_shape"], label="最大回撤校准形状")
    plt.title("最大回撤校准形状，仅用于拟合估算")
    plt.xlabel("日期")
    plt.ylabel("shape")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PNG_DIR / "hshylv_mdd_calibration_shape.png", dpi=150)
    plt.close()


def save_outputs(price_df: pd.DataFrame, fit_df: pd.DataFrame, summary_df: pd.DataFrame, errors_df: pd.DataFrame) -> None:
    price_csv = CSV_DIR / "hshylv_price_daily.csv"
    fit_csv = CSV_DIR / "hshylv_fitted_total_return_daily.csv"
    summary_csv = CSV_DIR / "hshylv_fitted_total_return_summary.csv"
    errors_csv = CSV_DIR / "errors_price_sources.csv"
    xlsx_path = OUT_DIR / "hshylv_fitted_total_return.xlsx"

    price_out = clean_daily_output(price_df)
    fit_out = clean_daily_output(fit_df)

    price_out.to_csv(price_csv, index=False, encoding="utf-8-sig")
    fit_out.to_csv(fit_csv, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    errors_df.to_csv(errors_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        fit_out.to_excel(writer, sheet_name="fitted_daily", index=False)
        price_out.to_excel(writer, sheet_name="price_daily", index=False)
        errors_df.to_excel(writer, sheet_name="source_errors", index=False)

    plot_outputs(fit_df)

    print("\n完成，输出文件：")
    print(f"  price_csv   : {price_csv.resolve()}")
    print(f"  fit_csv     : {fit_csv.resolve()}")
    print(f"  summary_csv : {summary_csv.resolve()}")
    print(f"  xlsx        : {xlsx_path.resolve()}")
    print(f"  png         : {(PNG_DIR / 'hshylv_price_vs_fitted_total_return.png').resolve()}")
    print(f"  shape_png   : {(PNG_DIR / 'hshylv_mdd_calibration_shape.png').resolve()}")
    print(f"  errors_csv  : {errors_csv.resolve()}")


def main() -> None:
    set_chinese_font()
    print("[MODE] HSHYLV fitted total-return curve")
    print(f"[FIT_MODE] {FIT_MODE}")
    print("[NOTE] 输出为拟合估算曲线，不是官方 HSHYLVDV/HSHYLVN 历史点位")
    print(f"[REFERENCE] base={REFERENCE_BASE_DATE}, ann={REFERENCE_TOTAL_RETURN_ANNUALIZED_PCT:.4f}%, mdd={REFERENCE_MAX_DRAWDOWN_PCT:.4f}%")
    print(f"[OUT] {OUT_DIR.resolve()}")

    try:
        price_df, errors_df = load_or_fetch_price_daily()
    except Exception as exc:
        errors_path = CSV_DIR / "errors_price_sources.csv"
        pd.DataFrame([{
            "source": "all",
            "symbol": PRICE_CODE,
            "error": f"{type(exc).__name__}: {exc}",
        }]).to_csv(errors_path, index=False, encoding="utf-8-sig")
        print("\n[ERROR] 无法获得 HSHYLV 价格指数历史日线，无法拟合。")
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        print(f"[ERROR CSV] {errors_path.resolve()}")
        return

    fit_df, summary_df = fit_curve(price_df)
    save_outputs(price_df, fit_df, summary_df, errors_df)

    row = summary_df.iloc[0]
    print("\n拟合摘要：")
    print(f"  参考基准日: {row['reference_base_date']}")
    print(f"  实际价格数据范围: {row['start_date']} -> {row['end_date']}, rows={int(row['rows'])}")
    print(f"  是否覆盖参考基准日: {row['price_data_covers_reference_base']}")
    print(f"  是否截断区间拟合: {row['is_truncated_range_fit']}")
    print(f"  价格指数年化: {row['price_annualized_return_pct']:.4f}%")
    print(f"  目标全收益年化: {row['reference_total_return_annualized_pct']:.4f}%")
    print(f"  拟合全收益年化: {row['fit_annualized_return_pct']:.4f}%")
    print(f"  年化差值: {row['fit_annualized_gap_pp']:+.8f} pp")
    print(f"  年化-only 最大回撤: {row['annualized_only_fit_max_drawdown_pct']:.4f}%")
    print(f"  目标最大回撤: {row['reference_max_drawdown_pct']:.4f}%")
    print(f"  拟合最大回撤: {row['fit_max_drawdown_pct']:.4f}%")
    print(f"  最大回撤差值: {row['fit_max_drawdown_gap_pp']:+.8f} pp")
    print(f"  最大回撤拟合状态: {row['mdd_fit_status']}")
    print(f"  mdd_shape_b: {row['mdd_shape_b']:.8f}")
    print(f"  日漂移因子: {row['daily_drift_factor']:.12f}")
    print(f"  警告: {row['fit_warning']}")
    print("\n注意：这条曲线只能标注为‘截断区间拟合全收益/估算全收益’，不能标注为官方全收益历史。")


if __name__ == "__main__":
    main()
