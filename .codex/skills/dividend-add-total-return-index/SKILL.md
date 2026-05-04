---
name: dividend-add-total-return-index
description: 在 fund 项目新增或修订红利、自由现金流等全收益指数时使用，包括官方代码核验、更新 earning.md、更新 fetch_dividend_total_return_indices.py、生成单指数小 skill、重跑 dividend_total_return_indices 和 publish_relative_returns、排除或加入 publish 指数并验证输出。只允许全收益/收益型代码，不使用价格指数、快照或拟合曲线兜底。
---

# 新增全收益指数流程

## 适用场景

用户要求新增指数到红利表格、收益图、`result/dividend_total_return_indices`、`result/publish_relative_returns`，或要求“生成对应小 skills”“落实增加指数流程”时使用本 skill。

必须同时遵守：

- `fund-conda-env`：所有 Python 命令使用 `conda run -n jijin ...`。
- `dividend-publish-relative-returns`：更新或核对按发布时间归零图时使用其收益口径和验证清单。
- `skill-creator`：创建或更新 skill 文件时只写必要的 `SKILL.md`、脚本和资产。

## 官方核验

新增指数前先从官方指数公司、交易所或指数文件核验，不把第三方行情名、快照或普通价格指数当作全收益源。

需要核验：

- 指数主代码、全称、简称。
- 基准日、发布日期、计价币种和加权方式；只把已核验字段写入 `fund/红利指数/earning.md`。
- 全收益/收益型候选代码。若不能确认候选代码是全收益或收益型，停止并说明 blocker，不用价格指数兜底。

中证指数常用接口：

```text
https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/<主代码>
https://www.csindex.com.cn/csindex-home/indexInfo/index-details-data?fileLang=1&indexCode=<主代码>
https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=<全收益代码>&startDate=YYYYMMDD&endDate=YYYYMMDD
```

中证 `perf/index-perf` 的日期参数必须是 `YYYYMMDD`。如果接口返回早于官方基准日的人工锚点，例如 `2000-01-01=3000`，在配置里设置 `history_start_date`，只从官方有效起点开始计算。

## 修改清单

1. 更新发布时间表：

   ```text
   fund/红利指数/earning.md
   ```

   只新增或修正本次涉及的指数行。发布日期用于 publish 图归零，必须来自官方资料。

2. 更新聚合抓取脚本：

   ```text
   scripts/fetch_dividend_total_return_indices.py
   ```

   在 `INDEXES` 中加入或修订条目：

   ```python
   {
       "name": "指数简称",
       "code": "主代码",
       "description_name": "指数全收益名称",
       "history_start_date": "YYYY-MM-DD",  # 仅在需要过滤人工锚点或限定历史起点时设置
       "candidates": [
           ("csindex", "全收益或收益型代码"),
       ],
   }
   ```

3. 生成或更新单指数小 skill：

   ```text
   .codex/skills/dividend-total-return-index-skills-per-index/skills/<slug>/
   ├── SKILL.md
   └── scripts/fetch_<slug>.py
   ```

   wrapper 脚本沿用现有模式：从 `dividend-total-return-common/scripts` 导入 `run_one`，定义 `INDEX_ITEM`，再调用 `run_one(INDEX_ITEM, wrapper_file=CURRENT_FILE)`。

   同步更新：

   ```text
   .codex/skills/dividend-total-return-index-skills-per-index/skills/run_all_dividend_total_return_index_skills.sh
   ```

   如果 `.codex` 目录创建失败，按沙箱提示申请写入权限后再创建目录，不要改到其他位置。

4. 如 publish 参与指数发生变化，更新：

   ```text
   scripts/plot_publish_relative_returns.py
   .codex/skills/dividend-publish-relative-returns/SKILL.md
   ```

   例如新增指数需要进入图表，或某指数需要加入 `DEFAULT_EXCLUDED_NAMES` 从 publish 中排除。

## 运行顺序

从项目根目录 `/home/usrname/data/fund` 执行。所有 Python 命令都用 `jijin` 环境：

```bash
conda run -n jijin python -m py_compile scripts/fetch_dividend_total_return_indices.py scripts/plot_publish_relative_returns.py
conda run -n jijin python -m py_compile .codex/skills/dividend-total-return-index-skills-per-index/skills/dividend-total-return-common/scripts/dividend_total_return_core.py
conda run -n jijin python -m py_compile .codex/skills/dividend-total-return-index-skills-per-index/skills/<slug>/scripts/fetch_<slug>.py
conda run -n jijin python .codex/skills/dividend-total-return-index-skills-per-index/skills/<slug>/scripts/fetch_<slug>.py
conda run -n jijin python scripts/fetch_dividend_total_return_indices.py
conda run -n jijin python scripts/plot_publish_relative_returns.py
```

如果要批量重跑所有单指数小 skill：

```bash
conda run -n jijin bash .codex/skills/dividend-total-return-index-skills-per-index/skills/run_all_dividend_total_return_index_skills.sh
```

## 验证清单

聚合输出：

```bash
conda run -n jijin python -c "import pandas as pd; s=pd.read_csv('result/dividend_total_return_indices/csv/dividend_total_return_summary.csv'); print(len(s), s['end_date'].max()); print(s[['name','code','source','symbol','start_date','end_date']].to_string(index=False))"
conda run -n jijin python -c "import pandas as pd; d=pd.read_csv('result/dividend_total_return_indices/csv/dividend_total_return_long.csv'); print(d['name'].nunique(), len(d), d['date'].max())"
```

检查新指数：

- `summary.csv` 有新指数，`source/symbol` 是核验过的全收益或收益型代码。
- `end_date` 到最新官方可得交易日。
- `daily.csv` 首日不早于官方有效起点；没有保留人工锚点。
- `errors.csv` 没有本次新增指数的未处理错误。

publish 输出：

```bash
find result/publish_relative_returns/png -maxdepth 1 -type f -name '*.png' | sort
find result/publish_relative_returns/png -maxdepth 1 -type f -name '*.png' | wc -l
conda run -n jijin python -c "import pandas as pd; s=pd.read_csv('result/publish_relative_returns/csv/publish_relative_return_summary.csv'); print(s['main_name'].nunique(), s['name'].nunique(), len(s)); print(s[['main_name','main_publish_date']].drop_duplicates().to_string(index=False))"
```

期望：

- 参与 publish 的指数为 `N` 个时，summary 为 `N x N` 行，PNG 为 `N` 张。
- 新增指数同时出现在 `main_name` 和 `name`，除非用户明确要求只作被比较曲线或排除。
- 被排除指数不出现在 `main_name`、`name` 或 PNG 文件名中。
- 图例按每张图的最终收益降序，主指数发布时间排序输出。

## 禁止事项

- 不用价格指数、普通 K 线、快照、东方财富/腾讯普通指数或新拟合曲线替代全收益历史。
- 不为了让图完整而合成、外推或手工填补缺失历史。
- 不改无关基金笔记、无关指数配置，且不回滚用户已有改动。
