# 纯模拟自适应实验演示

本演示运行一个中央服务、两个独立 Lab Agent 进程，通过本机 loopback TCP
通信。PC A 模拟激光器，PC B 模拟转台与光谱仪。没有真实仪器连接、设备
发现或收费模型调用。自动决策由确定性单共振峰策略完成，不代表 LLM 自主
科研能力；可选自然语言计划草稿与本闭环是两项不同功能。

## 一键运行

在项目目录执行：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[central,ai,dev]'
.venv/bin/python -m labos adaptive-demo --directory runtime/adaptive-01 --seed 42
```

命令本身代表操作者批准这次隔离的本地模拟。它创建模拟配置和独立凭证，
绑定 `127.0.0.1` 的临时端口，执行后关闭三个子进程。每次用新的输出目录，
避免覆盖实验记录。目录中含 `acceptance.json`、导出的 `.h5`、进程日志、
中央数据库、PC B 原始光谱缓存及独立凭证；不要整体公开配置目录。

默认种子 42 的实测结果如下，选峰使用的是扫描得到的数据：

| 轮次 | 扫描范围 / nm | 步长 / nm | 点数 | 观测峰位 / nm |
|---|---|---|---|---|
| 粗扫描 | 500–800 | 20 | 16 | 640 |
| 第一次细扫 | 600–680 | 5 | 17 | 635 |
| 第二次细扫 | 625–645 | 1 | 21 | 635 |

共 54 点，每点 128 通道。下一轮以观测最大值为中心，向两侧各取上轮的两
个步长，在上一轮范围内截断并向内对齐新网格；范围并非写死在演示脚本中。
每轮分析前先确认模拟光源已关光，中央设备预约持续保留。

改变隐藏共振峰并运行：

```bash
.venv/bin/python -m labos adaptive-demo --directory runtime/adaptive-02 --resonance-nm 707 --seed 42
```

相同粗扫描随后变为 `660–740 nm / 5 nm`、`695–715 nm / 1 nm`，最后找到
707 nm。模拟器的峰位参数仅用于生成数据及验收对照，不传给选峰策略。
同一种子、相同采集参数的光谱可逐值复现，时间戳和运行 ID 自然不同。

## 自动验收与检查数据

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
# 连续运行两次 635 nm、一次 707 nm；省略目录参数时每次创建新的临时目录
.venv/bin/python scripts/adaptive_acceptance.py
# 也可指定新的保留目录
.venv/bin/python scripts/adaptive_acceptance.py --directory runtime/adaptive-acceptance-01
# 回归原固定扫描和断网恢复
.venv/bin/python -m labos demo --directory runtime/fixed-regression-01 --full
.venv/bin/python scripts/network_fault_acceptance.py
```

验收检查：真实 TCP 的三进程/两 Agent；三轮实际测量与计划对应；相同种子
的光谱及决策完全一致；峰位改变后扫描范围也改变；局部原始数据保留；
HDF5 中完整决策记录、逐点轮次、模拟标记；结束后关光、零功率、释放预约。
GitHub Actions 执行 pytest、Ruff 和 TCP 自适应验收，并上传不含凭证的
HDF5、验收 JSON 与日志。Windows 实机验证不由 Linux 上的通过结果替代。

HDF5 中的关键路径：

- `/raw/counts`、`/raw/spectrum_axis_nm`：原始光谱。
- `/raw/wavelength_nm`、`/raw/point_index`、`/raw/round_index`：激发波长、全局序号、轮次；不同轮次可以重复测量同一坐标。
- `/metadata/plan`：最初批准的范围、功率、曝光及预算。
- `/metadata/measurements_json`：逐点 Agent、readback、采集驱动和时间信息。
- `/adaptive/events_json`：完整的批准、各轮预检查、观测分析、后续计划或终止原因；不受控制台最近 200 条事件限制。

顶层 `workflow_version` 为 `adaptive-resonance-0.1.0`；逐点采集仍使用原有
`polarization-0.1.0` 测量格式。选峰记录的 `sampling_half_step_nm` 仅表示
网格半步长，不是拟合误差或统计置信区间。

## 自动与人工的边界

| 操作 | 当前行为 |
|---|---|
| 信号积分、背景扣除、选峰 | 自动；读取已同步测量数据 |
| 后续范围与更小步长的选择 | 自动；确定性策略，限定在已批准范围内 |
| 后续模拟扫描 | 初始批准后自动执行，每轮再次预检查 |
| 初始启动 | 人工执行 `adaptive-demo`，或以操作者凭证显式提交批准的模拟 Plan |
| 暂停、继续、停止 | 操作者控制整个运行；暂停待处理时不会为下一轮重新开光 |
| UNKNOWN、watchdog 故障、中央重启 | 不自动重放或续跑；操作者核对并显式 reconcile |
| 真实仪器驱动与实验执行 | 本次不提供；未来接入、装置验证及 Start 仍需人工批准 |

API 沿用 `/api/preflight` 和 `/api/runs`。在 Plan 内增加以下字段，固定一个
偏振角，并令初始波长范围为 500–800、步长 20，即可请求本演示流程：

```json
{
  "adaptive": {
    "simulation_approved": true,
    "refinement_steps_nm": [5, 1],
    "max_total_points": 200,
    "min_contrast": 0.1
  }
}
```

使用 API 前，还需在中央登记配置与 PC B 配置的模拟光谱仪上设置相同的
`simulation_response`（例如 `peak_nm: 635, width_nm: 18, seed: 42`），并重启
模拟服务。`adaptive-demo` 会自动完成这项配置；未设置时仍是原固定扫描
模拟信号，不能假定其代表样品共振。

缺失或非布尔 `true` 的批准、Agent 凭证、超出登记的限制都会被拒绝。
`GET /api/runs/{run_id}/adaptive` 以操作者凭证读取完整历史。

## 安全约束与异常行为

最多五轮、总计最多 5000 点；每轮必须完整同步后才分析。功率、曝光、
角度不随选峰提高，下一轮网格在上一轮内，不能借自适应扩大批准范围。
平坦/低对比度信号、边界最大值、相近高度的多个峰、平台峰、非有限或
不完整数据都会拒绝细扫。本策略适合示范单个可分辨的共振峰；窄峰被粗
网格漏采或强噪声不保证定位，应修改初始实验设计后重新批准。

预算不足、下一轮预检查失败或分析异常会保留已同步数据并走原有安全
关闭流程。若关闭无法确认，预约保留，需人工恢复。HDF5 导出失败会记录
`HDF5_EXPORT_FAILED`，原始中央及 Agent 缓存仍保留；可用原有 export 接口重试。
