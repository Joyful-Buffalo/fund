---
name: csi-dividend-low-volatility-100-total-return
description: 抓取 中证红利低波动指数（100）全收益 的历史日线、日收益、累计收益、年化收益和最大回撤。只使用全收益/收益型代码，不使用价格指数、快照或拟合曲线兜底。
---

# 中证红利低波动指数（100）全收益 Skill

## 触发场景

当用户要求抓取、更新、核验或导出 **中证红利低波动指数（100）** 的全收益历史数据时，使用本 Skill。

常见说法包括：

- 中证红利低波动指数（100） 全收益
- 930955 全收益历史曲线
- 中证红利低波动指数（100） 每日涨跌表格
- 中证红利低波动指数（100） 年化收益 / 最大回撤
- 不要价格指数兜底

## 严格口径

- 指数名称：`中证红利低波动指数（100）`
- 价格/主代码：`930955`
- 只允许以下全收益/收益型候选：
- `rising99:H20955`
- `csindex:H20955`

禁止使用普通价格指数、恒生快照、东方财富普通指数 K 线、腾讯普通指数 K 线或拟合曲线替代。

## 脚本

```text
skills/csi-dividend-low-volatility-100-total-return/scripts/fetch_csi_dividend_low_volatility_100_total_return.py
```

## 运行方式

从项目根目录 `/home/usrname/data/fund` 运行：

```bash
cd "/home/usrname/data/fund"
conda activate jijin
python skills/csi-dividend-low-volatility-100-total-return/scripts/fetch_csi_dividend_low_volatility_100_total_return.py
```

## 输出

```text
result/dividend_total_return_index_skills/csi-dividend-low-volatility-100-total-return/
├── csi-dividend-low-volatility-100-total-return.xlsx
├── csv/
│   ├── csi-dividend-low-volatility-100-total-return_daily.csv
│   ├── csi-dividend-low-volatility-100-total-return_summary.csv
│   └── errors.csv
└── png/
```

## CSV 输出规则

daily CSV 只保留有信息增量的列。若 `open`、`high`、`low` 全为空或与 `close` 全列完全相同，或 `volume`、`amount` 全为空，写出前必须删除；`name`、`code`、`source`、`symbol`、`cache_version`、`reference_fit_*` 等列内全表同值的元数据列也不写入 daily，元数据保留在 summary。不要把官方接口返回的重复 OHLC 列原样保留。

## 维护规则

新增或修改候选源时，必须确认该代码是全收益/收益型代码。若免费源无法抓取，写入 `errors.csv`，不要用价格指数替代。
