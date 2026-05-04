---
name: hk-connect-high-dividend-yield-total-return
description: 抓取 港股通高股息 全收益 的历史日线、日收益、累计收益、年化收益和最大回撤。只使用全收益/收益型代码，不使用价格指数、快照或拟合曲线兜底。
---

# 港股通高股息全收益 Skill

## 触发场景

当用户要求抓取、更新、核验或导出 **港股通高股息** 的全收益历史数据时，使用本 Skill。

常见说法包括：

- 港股通高股息 全收益
- 中证港股通高股息投资指数 全收益
- 930914 全收益历史曲线
- 港股通高股息 每日涨跌表格
- 港股通高股息 年化收益 / 最大回撤
- 不要价格指数兜底

## 严格口径

- 指数名称：`港股通高股息`
- 指数全称：`中证港股通高股息投资指数`
- 价格/主代码：`930914`
- 基准日：`2014-11-14`
- 只允许以下全收益/收益型候选：
- `csindex:H20914`

禁止使用普通价格指数、恒生快照、东方财富普通指数 K 线、腾讯普通指数 K 线或拟合曲线替代。

注意：中证接口可能返回 `2000-01-01=3000` 的锚点，本 skill 只从官方基准日 `2014-11-14` 起保留和计算。

## 脚本

```text
skills/hk-connect-high-dividend-yield-total-return/scripts/fetch_hk_connect_high_dividend_yield_total_return.py
```

## 运行方式

从项目根目录 `/home/usrname/data/fund` 运行：

```bash
cd "/home/usrname/data/fund"
conda activate jijin
python skills/hk-connect-high-dividend-yield-total-return/scripts/fetch_hk_connect_high_dividend_yield_total_return.py
```

## 输出

```text
result/dividend_total_return_index_skills/hk-connect-high-dividend-yield-total-return/
├── hk-connect-high-dividend-yield-total-return.xlsx
├── csv/
│   ├── hk-connect-high-dividend-yield-total-return_daily.csv
│   ├── hk-connect-high-dividend-yield-total-return_summary.csv
│   └── errors.csv
└── png/
```

## CSV 输出规则

daily CSV 只保留有信息增量的列。若 `open`、`high`、`low` 全为空或与 `close` 全列完全相同，或 `volume`、`amount` 全为空，写出前必须删除；`name`、`code`、`source`、`symbol`、`cache_version`、`reference_fit_*` 等列内全表同值的元数据列也不写入 daily，元数据保留在 summary。不要把官方接口返回的重复 OHLC 列原样保留。

## 维护规则

新增或修改候选源时，必须确认该代码是全收益/收益型代码。若免费源无法抓取，写入 `errors.csv`，不要用价格指数替代。
