---
name: fund-conda-env
description: 在 fund 项目需要运行 Python 代码、脚本、测试、Notebook、数据处理或包管理命令时使用。本技能要求所有 Python 执行都进入 `jijin` conda 环境，禁止直接使用系统 Python；非交互命令优先使用 `conda run -n jijin ...`。
---

# fund 项目运行环境

## 核心规则

在 fund 项目中，所有 Python 相关命令都必须在 `jijin` conda 环境中运行。不要直接使用系统 Python。

除非用户给出更具体的工作目录，否则使用这个项目根目录：

```bash
/home/usrname/data/fund
```

## 命令格式

优先使用非交互式 `conda run` 命令：

```bash
conda run -n jijin python ...
conda run -n jijin python scripts/example.py
conda run -n jijin python -m pytest
conda run -n jijin pytest
conda run -n jijin pip ...
```

只有在明确需要交互式 shell 会话时，才使用 `conda activate jijin`。普通 Codex 命令执行场景使用 `conda run -n jijin ...`。

## 禁止命令

不要从系统环境直接运行 Python 相关命令：

```bash
python ...
python3 ...
pip ...
pytest ...
ipython ...
jupyter ...
```

即使只是一次性快速检查，也要包装到 `jijin` 环境中：

```bash
conda run -n jijin python -c "..."
```

## 失败处理

如果 `jijin` 环境缺少某个包或命令，不要退回系统 Python。报告缺失依赖；需要安装或运行时，也应在用户同意后通过 `jijin` conda 环境处理。
