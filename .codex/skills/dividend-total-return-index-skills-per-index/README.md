# Dividend Total Return Index Skills

本包将每一个指数落实为一个独立 Skill。

- 每个指数一个目录。
- 每个目录有独立 `SKILL.md`。
- 每个目录有独立抓取脚本。
- 公共抓取逻辑放在 `dividend-total-return-common/scripts/dividend_total_return_core.py`。
- 已删除恒生红利低波动指数（50）/ HSHYLV，不做拟合，不用价格指数替代。
- daily CSV 写出前必须删除无信息增量列：`open`、`high`、`low` 若全为空或与 `close` 全列完全相同则不写出；`volume`、`amount` 若全为空则不写出；`name`、`code`、`source`、`symbol`、`cache_version`、`reference_fit_*` 等列内全表同值的元数据列也不写入 daily，元数据保留在 summary。

| 序号 | Skill | 指数 | 代码 |
| --- | --- | --- | --- |
| 1 | `sh-dividend-50-total-return` | 上证红利指数（50） | `000015` |
| 2 | `csi-dividend-100-total-return` | 中证红利指数（100） | `000922` |
| 3 | `central-soe-dividend-50-total-return` | 央企红利指数（50） | `000825` |
| 4 | `state-owned-enterprise-dividend-100-total-return` | 国企红利指数（100） | `000824` |
| 5 | `hk-connect-central-soe-dividend-48-total-return` | 港股通央企红利指数（48） | `931722` |
| 6 | `consumer-dividend-50-total-return` | 消费红利指数（50） | `H30094` |
| 7 | `leading-dividend-50-total-return` | 龙头红利指数（50） | `995082` |
| 8 | `dividend-quality-50-total-return` | 红利质量指数（50） | `931468` |
| 9 | `hk-dividend-30-total-return` | 港股红利指数（30） | `930914` |
| 10 | `csi-dividend-low-volatility-50-total-return` | 中证红利低波动指数（50） | `H30269` |
| 11 | `csi-dividend-low-volatility-100-total-return` | 中证红利低波动指数（100） | `930955` |
| 12 | `csi-hksh-dividend-growth-low-volatility-100-total-return` | 沪港深红利成长低波动指数（100） | `931157` |
| 13 | `csi-free-cash-flow-100-total-return` | 中证全指自由现金流指数（100） | `932365` |
| 14 | `cni-free-cash-flow-100-total-return` | 国证自由现金流指数（100） | `980092` |

## 单个指数运行示例

```bash
cd "/home/usrname/data/fund"
conda activate jijin
python skills/csi-dividend-100-total-return/scripts/fetch_csi_dividend_100_total_return.py
```

## 批量运行

```bash
cd "/home/usrname/data/fund"
conda activate jijin
bash skills/run_all_dividend_total_return_index_skills.sh
```
