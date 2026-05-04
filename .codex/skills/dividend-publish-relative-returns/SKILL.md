---
name: dividend-publish-relative-returns
description: 在 fund 项目绘制、更新或核对红利指数/基金“按发布时间归零”的全收益相对收益曲线时使用。适用于用户要求按主指数发布时间生成图片、按最终收益排序图例、按主指数发布时间排序输出图片、统计各指数自其发布时间或主发布时间起的收益，而不是用指数基准日或更早历史归零。
---

# 红利发布时间相对收益图

## 核心脚本

优先使用项目脚本：

```bash
conda run -n jijin python scripts/plot_publish_relative_returns.py
```

遵守 `fund-conda-env`：在 fund 项目中运行 Python、测试或数据处理命令时必须使用 `conda run -n jijin ...`，不要直接用系统 Python。

脚本默认读取：

- 发布时间表：`fund/红利指数/earning.md`
- 单指数 skill 输出：`result/dividend_total_return_index_skills`
- 旧版日线目录：`result/index_return_curve/csv`，其次 `result/dividend_total_return_indices/csv`
- 同一指数存在多个日线源时，选择 `last_date` 最新的源；日期相同则优先单指数 skill 输出
- 恒生红利低波动拟合曲线：`result/hsi_hshylv_total_return_fit/csv/hshylv_fitted_total_return_daily.csv`
- 默认排除：`消费红利指数（50）`

脚本默认输出：

- 图片：`result/publish_relative_returns/png`
- 统计：`result/publish_relative_returns/csv/publish_relative_return_summary.csv`
- 明细：`result/publish_relative_returns/csv/publish_relative_return_long.csv`

## 收益口径

每张图以一个主指数为主图，横轴从主指数发布时间开始。

每条曲线的收益起点必须是：

```text
requested_return_start_date = max(主指数发布时间, 本指数发布时间)
base_date = requested_return_start_date 之后首个有日线点位的日期
relative_return = close / base_close - 1
```

注意：

- 不使用指数基准日归零。
- 不使用 `requested_return_start_date` 之前的最近收盘价作基准。
- 已经在主指数发布时间前发布的指数，按主指数发布时间之后首个可用日归零。
- 晚于主指数发布时间才发布的指数，按本指数发布时间之后首个可用日归零。
- 如果某指数在收益起点之后没有任何日线，则跳过该曲线，不要用快照或价格指数兜底。
- 统计表里的 `cum_return_pct`、`annualized_return_pct`、`max_drawdown_pct` 也必须基于同一个 `base_date` 之后的数据。

## 绘图和排序

每张图绘制前，按该图中每条曲线最后一个 `relative_return_pct` 降序排序；最后收益最高的排在图例最前。

主指数仍用黑色粗线标注“（主）”，但图例位置也服从最终收益排序。

图片输出顺序按主指数发布时间升序，文件名必须带序号和发布日期前缀：

```text
01_2005-01-04_上证红利指数_50_发布日起全收益相对收益.png
02_2008-05-26_中证红利指数_100_发布日起全收益相对收益.png
...
```

生成新图前应清理旧的 `*_发布日起全收益相对收益.png`，避免目录里混入不带前缀或旧口径图片。

## 恒生红利低波动

恒生红利低波动指数（50）当前使用项目已有拟合全收益曲线，不是官方 HSHYLVDV/HSHYLVN 历史日线。

要求：

- 可以绘制，但必须在输出字段 `data_note` 中保留拟合说明。
- 不要把它称为官方全收益历史。
- 不要用价格指数、快照或新的拟合逻辑替换现有口径，除非用户明确要求重新研究数据源。

## 验证清单

运行脚本后至少检查：

```bash
find result/publish_relative_returns/png -maxdepth 1 -type f -name '*.png' | sort
find result/publish_relative_returns/png -maxdepth 1 -type f -name '*.png' | wc -l
conda run -n jijin python -c "import pandas as pd; s=pd.read_csv('result/publish_relative_returns/csv/publish_relative_return_summary.csv'); print(s['main_name'].nunique(), s['name'].nunique(), len(s)); print(s[['main_name','main_publish_date']].drop_duplicates().to_string(index=False))"
```

期望：

- 图片数量等于参与 publish 的主指数数量。
- 汇总表为 N x N 行数据，N 为参与 publish 的指数数量。
- 主图顺序按 `main_publish_date` 升序。
- 抽样检查早期主指数时，晚发布指数从自己的发布时间归零；已发布指数从主指数发布时间归零。例如中证红利作为主指数时，上证红利和中证红利都从 `2008-05-26` 归零，龙头红利从 `2021-12-17` 归零。

## 修改脚本时

保持脚本行为可审计：

- 不联网抓新数据，除非用户明确要求更新源数据。
- 不把价格指数、快照或临时拟合曲线混入严格全收益口径。
- 不改变 `earning.md` 的发布时间，除非用户明确要求修订并给出依据。
- 修改后必须重新运行脚本并做验证清单。
