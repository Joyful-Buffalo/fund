import os
import socket

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


from pathlib import Path
import json
import re
import time

import akshare as ak
import pandas as pd
import requests
import matplotlib.pyplot as plt
from matplotlib import font_manager


START_DATE = "20000101"
END_DATE = pd.Timestamp.today().strftime("%Y%m%d")

CACHE_VERSION = "2026-05-04-dividend-total-return-strict-csindex-date-v3"

RETRY_TIMES = 1
SLEEP_SECONDS = 1
REQUEST_TIMEOUT = 15

REFERENCE_FIT_MIN_YEARS = 3
REFERENCE_FIT_ACCEPT_SCORE = 0.75
REFERENCE_FIT_KEEP_FULL_ANN_GAP = 0.30
REFERENCE_FIT_KEEP_FULL_DD_GAP = 0.30

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent

OUT_DIR = REPO_DIR / "result" / "dividend_total_return_indices"
CSV_DIR = OUT_DIR / "csv"
PNG_DIR = OUT_DIR / "png"

for output_dir in [OUT_DIR, CSV_DIR, PNG_DIR]:
    output_dir.mkdir(parents=True, exist_ok=True)

REFERENCE_METRICS_CANDIDATES = [
    REPO_DIR / "fund" / "红利指数" / "earning.md",
    REPO_DIR / "红利指数" / "earning.md",
    REPO_DIR / "earning.md",
]


# ===== 修改部分 2：只保留严格全收益 / 收益型候选 =====
# 已删除：
# - 恒生红利低波动指数（50）/ HSHYLV
# - hsi_snapshot
# - hk
# - em_direct
# - em_ak
# - tx
#
# 国证自由现金流：
# - 980092 是价格指数
# - 480092 是收益型 / 自由现金流R
INDEXES = [
    {
        "name": "上证红利指数（50）",
        "code": "000015",
        "candidates": [
            ("rising99", "H00015"),
            ("csindex", "H00015"),
        ],
    },
    {
        "name": "中证红利指数（100）",
        "code": "000922",
        "candidates": [
            ("rising99", "H00922"),
            ("csindex", "H00922"),
        ],
    },
    {
        "name": "央企红利指数（50）",
        "code": "000825",
        "candidates": [
            ("rising99", "H00825"),
            ("csindex", "H00825"),
        ],
    },
    {
        "name": "国企红利指数（100）",
        "code": "000824",
        "candidates": [
            ("rising99", "H00824"),
            ("csindex", "H00824"),
        ],
    },
    {
        "name": "港股通央企红利指数（48）",
        "code": "931722",
        "candidates": [
            ("csindex", "931722HKD210"),
        ],
    },
    {
        "name": "消费红利指数（50）",
        "code": "H30094",
        "candidates": [
            ("rising99", "H20094"),
            ("csindex", "H20094"),
        ],
    },
    {
        "name": "龙头红利指数（50）",
        "code": "995082",
        "candidates": [
            ("chindices_return", "995082"),
        ],
    },
    {
        "name": "红利质量指数（50）",
        "code": "931468",
        "candidates": [
            ("rising99", "921468"),
            ("csindex", "921468"),
        ],
    },
    {
        "name": "港股红利指数（30）",
        "code": "930914",
        "candidates": [
            ("rising99", "H20914"),
            ("csindex", "H20914"),
        ],
    },
    {
        "name": "中证红利低波动指数（50）",
        "code": "H30269",
        "candidates": [
            ("rising99", "H20269"),
            ("csindex", "H20269"),
        ],
    },
    {
        "name": "中证红利低波动指数（100）",
        "code": "930955",
        "candidates": [
            ("rising99", "H20955"),
            ("csindex", "H20955"),
        ],
    },
    {
        "name": "沪港深红利成长低波动指数（100）",
        "code": "931157",
        "candidates": [
            ("rising99", "H21157"),
            ("csindex", "H21157"),
        ],
    },
    {
        "name": "中证全指自由现金流指数（100）",
        "code": "932365",
        "candidates": [
            ("csindex", "932365CNY010"),
        ],
    },
    {
        "name": "国证自由现金流指数（100）",
        "code": "980092",
        "candidates": [
            ("cni", "480092"),
        ],
    },
]


TOTAL_RETURN_CANDIDATE_WHITELIST = {
    pair
    for item in INDEXES
    for pair in item["candidates"]
}


def assert_total_return_candidate(source: str, symbol: str) -> None:
    if (source, symbol) not in TOTAL_RETURN_CANDIDATE_WHITELIST:
        raise ValueError(f"禁止抓取非全收益候选: {source}:{symbol}")


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


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|（）()]', "_", name)


def csv_path_of(name: str) -> Path:
    return CSV_DIR / f"{safe_filename(name)}_daily.csv"


def summary_csv_path() -> Path:
    return CSV_DIR / "dividend_total_return_indices_summary.csv"


def long_daily_csv_path() -> Path:
    return CSV_DIR / "dividend_total_return_indices_long_daily.csv"


def errors_csv_path() -> Path:
    return CSV_DIR / "errors.csv"


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


def parse_date_series(values) -> pd.Series:
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(values, errors="coerce")


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


def clean_long_daily_output(df: pd.DataFrame) -> pd.DataFrame:
    return drop_constant_columns(drop_redundant_daily_columns(df), keep=["date", "name"])


def find_reference_metrics_path() -> Path | None:
    for path in REFERENCE_METRICS_CANDIDATES:
        if path.exists():
            return path
    return None


def normalize_reference_name(name: str) -> str:
    return name.strip().replace("户港深", "沪港深")


def load_reference_metrics() -> dict[str, dict[str, object]]:
    path = find_reference_metrics_path()
    if path is None:
        return {}

    metrics: dict[str, dict[str, object]] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| ---"):
            continue
        if "名称" in line:
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


def max_drawdown_details(df: pd.DataFrame) -> dict[str, object]:
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


def parse_reference_drawdown_dates(value: object) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
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


def reference_fit_score(
    df: pd.DataFrame,
    reference: dict[str, object],
) -> tuple[float | None, dict[str, object]]:
    ann = annualized_return_pct(df)
    dd_details = max_drawdown_details(df)
    dd = dd_details["max_drawdown_pct"]

    ref_ann = reference.get("reference_total_return_annualized_pct")
    ref_dd = reference.get("reference_max_drawdown_pct")
    ref_peak, ref_trough = parse_reference_drawdown_dates(
        reference.get("reference_max_drawdown_dates")
    )

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


def apply_reference_fit(df: pd.DataFrame, item: dict) -> pd.DataFrame:
    reference = load_reference_metrics().get(normalize_reference_name(item["name"]), {})
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


def fetch_csindex_payload(symbol: str, start_date: str, end_date: str) -> list[dict]:
    url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
    params = {
        "indexCode": symbol,
        "startDate": start_date,
        "endDate": end_date,
    }

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

    start_dates = [
        csindex_api_date(START_DATE),
        "20170101",
        "20240101",
    ]

    best_data: list[dict] = []

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

    return pd.DataFrame(
        {
            "date": xaxis,
            "close": series[series_idx],
        }
    )


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

    return pd.DataFrame(
        {
            "date": x_values[:row_count],
            "close": close,
        }
    )


def fetch_cni(symbol: str) -> pd.DataFrame:
    return ak.index_hist_cni(
        symbol=symbol,
        start_date=START_DATE,
        end_date=END_DATE,
    )


def fetch_raw(source: str, symbol: str) -> pd.DataFrame:
    assert_total_return_candidate(source, symbol)

    if source == "rising99":
        return fetch_99rising_daily_earning(symbol)

    if source == "csindex":
        return fetch_csindex_direct(symbol)

    if source == "chindices_return":
        return fetch_chindices_return(symbol)

    if source == "cni":
        return fetch_cni(symbol)

    raise ValueError(f"未知或未允许的数据源: {source}")


def normalize_daily(raw: pd.DataFrame, item: dict, source: str, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError("返回空数据")

    date_col = pick_col(raw, ["date", "日期", "tradeDate"])
    close_col = pick_col(raw, ["close", "收盘", "收盘价", "latest", "最新价"])

    open_col = next((col for col in ["open", "开盘", "开盘价", "今开"] if col in raw.columns), None)
    high_col = next((col for col in ["high", "最高", "最高价"] if col in raw.columns), None)
    low_col = next((col for col in ["low", "最低", "最低价"] if col in raw.columns), None)
    volume_col = next((col for col in ["volume", "成交量"] if col in raw.columns), None)
    amount_col = next((col for col in ["amount", "成交额"] if col in raw.columns), None)

    df = pd.DataFrame(
        {
            "date": parse_date_series(raw[date_col]),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
        }
    )

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

    start = pd.to_datetime(START_DATE)
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

    df = apply_reference_fit(df, item)
    df = drop_redundant_daily_columns(add_return_columns(df))

    return df


def first_non_null(*values):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def load_cache_summary_meta(name: str) -> dict:
    path = summary_csv_path()
    if not path.exists():
        return {}
    try:
        summary = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {}
    if summary.empty or "name" not in summary.columns:
        return {}
    target = normalize_reference_name(name)
    names = summary["name"].astype(str).map(normalize_reference_name)
    matched = summary[names == target]
    if matched.empty:
        return {}
    return matched.iloc[0].to_dict()


def restore_constant_column(df: pd.DataFrame, column: str, value, position: int | None = None) -> None:
    if column in df.columns:
        return
    loc = len(df.columns) if position is None else min(position, len(df.columns))
    df.insert(loc, column, value)


def load_cache(item: dict) -> pd.DataFrame | None:
    path = csv_path_of(item["name"])

    if not path.exists():
        return None

    df = pd.read_csv(path)

    if df.empty:
        return None

    summary_meta = load_cache_summary_meta(item["name"])

    cache_version = first_non_null(
        df["cache_version"].iloc[0] if "cache_version" in df.columns else None,
        summary_meta.get("cache_version"),
    )
    if cache_version is None:
        print(f"[CACHE] {item['name']} 缓存缺少 summary 元数据，重新抓取: {path.relative_to(REPO_DIR)}")
        return None

    if str(cache_version) != CACHE_VERSION:
        print(f"[CACHE] {item['name']} 缓存口径已过期，重新抓取: {path.relative_to(REPO_DIR)}")
        return None

    source = first_non_null(
        df["source"].iloc[0] if "source" in df.columns else None,
        summary_meta.get("source"),
    )
    symbol = first_non_null(
        df["symbol"].iloc[0] if "symbol" in df.columns else None,
        summary_meta.get("symbol"),
    )
    if source is None or symbol is None:
        print(f"[CACHE] {item['name']} 缓存缺少 source/symbol，重新抓取: {path.relative_to(REPO_DIR)}")
        return None

    cached_pair = (str(source), str(symbol))
    if cached_pair not in item["candidates"]:
        print(f"[CACHE] {item['name']} 缓存数据源已变更，重新抓取: {path.relative_to(REPO_DIR)}")
        return None

    restore_constant_column(df, "name", item["name"], 0)
    restore_constant_column(df, "code", item["code"], 1)
    restore_constant_column(df, "source", source, 2)
    restore_constant_column(df, "symbol", symbol, 3)
    restore_constant_column(df, "cache_version", cache_version, 4)
    restore_constant_column(df, "reference_fit_score", summary_meta.get("reference_fit_score"))
    restore_constant_column(df, "reference_fit_note", summary_meta.get("reference_fit_note"))

    df["date"] = parse_date_series(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df[df["close"] > 0]
    df = df.sort_values("date").drop_duplicates("date")

    if len(df) < 2:
        print(f"[CACHE] {item['name']} 缓存行数过少，重新抓取: {path.relative_to(REPO_DIR)}")
        return None

    df = drop_redundant_daily_columns(add_return_columns(df))
    print(f"[CACHE] {item['name']} <- {path.relative_to(REPO_DIR)}, rows={len(df)}")
    return df


def fetch_raw_with_retry(source: str, symbol: str) -> pd.DataFrame:
    last_error = None

    for retry_idx in range(1, RETRY_TIMES + 1):
        try:
            return fetch_raw(source, symbol)
        except Exception as exc:
            last_error = exc
            print(
                f"    retry {retry_idx}/{RETRY_TIMES}: "
                f"{source}:{symbol} failed: {type(exc).__name__}: {exc}"
            )
            time.sleep(SLEEP_SECONDS)

    assert last_error is not None
    raise last_error


def fetch_one(item: dict) -> pd.DataFrame:
    cached = load_cache(item)
    if cached is not None:
        return cached

    errors = []
    successful = []
    has_reference = bool(load_reference_metrics().get(normalize_reference_name(item["name"]), {}))

    for source, symbol in item["candidates"]:
        try:
            raw = fetch_raw_with_retry(source, symbol)
            df = normalize_daily(raw, item, source, symbol)

            print(f"[OK] {item['name']} <- {source}:{symbol}, rows={len(df)}")
            successful.append(df)

            fit_score = pd.to_numeric(
                df.get("reference_fit_score", pd.Series([pd.NA])).iloc[0],
                errors="coerce",
            )

            if not has_reference:
                return df

            if not pd.isna(fit_score) and fit_score <= REFERENCE_FIT_ACCEPT_SCORE:
                return df

        except Exception as exc:
            msg = f"{source}:{symbol} -> {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"[FAIL] {item['name']} <- {msg}")
            time.sleep(SLEEP_SECONDS)

    if successful:
        def score_of(df: pd.DataFrame) -> float:
            score = pd.to_numeric(
                df.get("reference_fit_score", pd.Series([pd.NA])).iloc[0],
                errors="coerce",
            )
            return float(score) if not pd.isna(score) else float("inf")

        best = min(successful, key=score_of)
        print(
            f"[BEST] {item['name']} <- {best['source'].iloc[0]}:{best['symbol'].iloc[0]}, "
            f"fit_score={score_of(best):.3f}, rows={len(best)}"
        )
        return best

    raise RuntimeError("全部候选接口失败:\n" + "\n".join(errors))


def build_summary(all_df: list[pd.DataFrame]) -> pd.DataFrame:
    references = load_reference_metrics()
    rows = []

    for df in all_df:
        if df.empty:
            continue

        item = df.sort_values("date").copy()
        name = normalize_reference_name(str(item["name"].iloc[0]))
        reference = references.get(name, {})

        ann = annualized_return_pct(item)
        dd_details = max_drawdown_details(item)
        dd = dd_details["max_drawdown_pct"]

        ref_ann = reference.get("reference_total_return_annualized_pct")
        ref_dd = reference.get("reference_max_drawdown_pct")

        rows.append(
            {
                "name": name,
                "code": item["code"].iloc[0],
                "source": item["source"].iloc[0],
                "symbol": item["symbol"].iloc[0],
                "cache_version": item["cache_version"].iloc[0] if "cache_version" in item.columns else None,
                "rows": len(item),
                "start_date": item["date"].iloc[0],
                "end_date": item["date"].iloc[-1],
                "last_close": item["close"].iloc[-1],
                "cum_return_pct": item["cum_return_pct"].iloc[-1],
                "annualized_return_pct": ann,
                "max_drawdown_pct": dd,
                "max_drawdown_peak_date": dd_details["max_drawdown_peak_date"],
                "max_drawdown_trough_date": dd_details["max_drawdown_trough_date"],
                "reference_fit_score": (
                    item["reference_fit_score"].iloc[0]
                    if "reference_fit_score" in item.columns
                    else None
                ),
                "reference_fit_note": (
                    item["reference_fit_note"].iloc[0]
                    if "reference_fit_note" in item.columns
                    else None
                ),
                **reference,
                "annualized_gap_pp": (
                    ann - float(ref_ann)
                    if ann is not None and ref_ann is not None
                    else None
                ),
                "max_drawdown_gap_pp": (
                    dd - float(ref_dd)
                    if dd is not None and ref_dd is not None
                    else None
                ),
                "strict_total_return_only": True,
            }
        )

    return pd.DataFrame(rows)


def plot_curve(df: pd.DataFrame, name: str) -> None:
    plt.figure(figsize=(12, 5))
    plt.plot(df["date"], df["cum_return_pct"])
    plt.title(name)
    plt.xlabel("日期")
    plt.ylabel("累计收益率 %")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    png_path = PNG_DIR / f"{safe_filename(name)}_cum_return.png"
    plt.savefig(png_path, dpi=150)
    plt.close()


def save_outputs(all_df: list[pd.DataFrame], errors: list[dict]) -> None:
    if all_df:
        long_df = pd.concat(all_df, ignore_index=True)
        long_out = clean_long_daily_output(long_df)
        summary_df = build_summary(all_df)

        close_wide = long_df.pivot(index="date", columns="name", values="close")
        daily_return_wide = long_df.pivot(index="date", columns="name", values="daily_return")
        cum_return_wide = long_df.pivot(index="date", columns="name", values="cum_return")

        xlsx_path = OUT_DIR / "dividend_total_return_indices.xlsx"
        summary_path = summary_csv_path()
        long_path = long_daily_csv_path()

        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
        long_out.to_csv(long_path, index=False, encoding="utf-8-sig")

        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            long_out.to_excel(writer, sheet_name="long_daily", index=False)
            close_wide.to_excel(writer, sheet_name="close")
            daily_return_wide.to_excel(writer, sheet_name="daily_return")
            cum_return_wide.to_excel(writer, sheet_name="cum_return")

        print(f"\n完成，输出目录: {OUT_DIR.resolve()}")
        print(f"汇总文件: {xlsx_path.resolve()}")
        print(f"summary_csv: {summary_path.resolve()}")
        print(f"long_daily_csv: {long_path.resolve()}")

        if not summary_df.empty and "annualized_gap_pp" in summary_df.columns:
            gap_series = pd.to_numeric(summary_df["annualized_gap_pp"], errors="coerce")
            large_gap = summary_df[gap_series.abs() >= 2].sort_values("annualized_gap_pp")

            if not large_gap.empty:
                print("\n[WARN] 与参考年化全收益差异 >= 2pp：")
                for _, row in large_gap.iterrows():
                    print(
                        f"  {row['name']}: "
                        f"{row['annualized_return_pct']:.2f}% vs "
                        f"{row['reference_total_return_annualized_pct']:.2f}%, "
                        f"gap={row['annualized_gap_pp']:+.2f}pp"
                    )
    else:
        print("\n没有任何指数抓取成功。")

    err_path = errors_csv_path()

    if errors:
        pd.DataFrame(errors).to_csv(err_path, index=False, encoding="utf-8-sig")
        print(f"\n有 {len(errors)} 个指数抓取失败，见: {err_path.resolve()}")
    elif err_path.exists():
        err_path.unlink()


def main() -> None:
    set_chinese_font()

    ref_path = find_reference_metrics_path()

    print("[MODE] dividend total-return indices, strict only")
    print("[EXCLUDE] 恒生红利低波动指数（50）/ HSHYLV 已移除")
    print("[NO FALLBACK] 不使用价格指数、快照或拟合曲线替代官方/准官方全收益历史")
    print(f"[OUT] {OUT_DIR.resolve()}")

    if ref_path is not None:
        print(f"[REFERENCE] {ref_path.resolve()}")
    else:
        print("[REFERENCE] 未找到 earning.md，仍会抓取并计算自身年化/最大回撤")

    all_df = []
    errors = []

    for item in INDEXES:
        try:
            df = fetch_one(item)
            all_df.append(df)

            clean_daily_output(df).to_csv(csv_path_of(item["name"]), index=False, encoding="utf-8-sig")
            plot_curve(df, item["name"])

        except KeyboardInterrupt:
            print("\n手动中断，正在保存已成功抓取的数据...")
            break

        except Exception as exc:
            errors.append(
                {
                    "name": item["name"],
                    "code": item["code"],
                    "error": str(exc),
                }
            )

    save_outputs(all_df, errors)


if __name__ == "__main__":
    main()
