# LabOS MVP

中央规划、本地执行、可追溯数据。首版支持一台中央服务器、两台主动连接服务器的 Windows/Linux Agent 和三类**模拟仪器**。

已经实现：独立凭证、会话隔离、预检查、资源独占、扫描、暂停/继续/停止、UNKNOWN 结果处理、本地 watchdog、数据缓存重传、HDF5 导出、中文控制台、可选 OpenAI 计划草稿。SSH 不是运行依赖。

真实仪器驱动尚未启用；型号、SDK、连接方式和装置验证齐备后再接入。模拟数据均有显式标记。

新增：**纯模拟自适应共振扫描闭环**。两个 Lab Agent 先执行 500–800 nm 粗扫描，中央策略根据实际上传的光谱选峰，再自动缩小范围、依次用 5 nm 和 1 nm 步长扫描。沿用原有预检查、资源独占、watchdog、日志、缓存上传及 HDF5。策略为确定性算法，无需 OpenAI/API key。详见 [运行与审批边界](docs/ADAPTIVE_DEMO_ZH.md)。

## 开发环境与本机验收

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[central,ai,dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m labos demo --directory runtime/demo-01
# 完整 399 点实验；使用新的输出目录
.venv/bin/python -m labos demo --directory runtime/full-demo-01 --full
# 自适应模拟；每次使用新的输出目录
.venv/bin/python -m labos adaptive-demo --directory runtime/adaptive-01
# 将隐藏的模拟峰移到 707 nm，观察后续范围随数据改变
.venv/bin/python -m labos adaptive-demo --directory runtime/adaptive-02 --resonance-nm 707
# 自动验收：两次相同种子的实验 + 一次移动共振峰（自动创建新目录）
.venv/bin/python scripts/adaptive_acceptance.py
```

## 部署

先看 [中文部署指南](docs/DEPLOYMENT_ZH.md)、[网络方案](docs/NETWORK_ZH.md) 和 [真实仪器接入](docs/HARDWARE_ZH.md)。交付文件位于 `dist/`。PC 暂未安排时不需要生成真实部署凭证。

例：中央服务器在专用 LAN/VPN 的 `192.168.1.10:8000`：

```bash
.venv/bin/python -m labos init --directory deployments/lab-01 \
  --server-url http://192.168.1.10:8000 --allow-http --host 0.0.0.0
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-a/config.yaml \
  --windows-runtime dist/delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-a.zip
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-b/config.yaml \
  --windows-runtime dist/delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-b.zip
.venv/bin/python -m labos central --config deployments/lab-01/central/config.yaml
```

分别复制 `pc-a.zip` / `pc-b.zip`，解压，执行 `Doctor.ps1` 验证，再双击 `Start-Agent.cmd`。不要把 `central/config.yaml` 或 `operator.token` 复制到实验室 PC。

中央页面在 `http://192.168.1.10:8000`；操作凭证读取 `deployments/lab-01/central/operator.token`。填写参数、预检查、点击 Start。数据保留在中央和采集 PC 各自的 `data/`。

## 构建交付

```bash
.venv/bin/python scripts/build_windows_runtime.py
.venv/bin/python scripts/build_delivery.py --windows-runtime dist/delivery/windows-x64-runtime.zip
```

网络采用 HTTP(S) 出站轮询；只有中央服务器需要被 PC 访问。连接跨 VLAN/NAT 时使用可路由的专用 VPN 或可访问的 HTTPS 中央入口。Windows 任务计划程序支持登录启动或经管理员选择的开机启动。

## 边界

中央 SQLite 与执行器要求单实例；不使用 uvicorn 多 worker/reload。中断的实验需要核对，不自动续跑未知物理动作。本地 watchdog 不能替代硬件联锁或断电保护。此版本没有通用 YAML 执行器、自动生成生产驱动、任意 Python/SCPI 接口和硬件快速同步。

OpenAI 可选：中央配置 `openai_model` 并设置 `OPENAI_API_KEY`，界面才能生成自然语言计划草稿。模型名称由部署者配置；草稿仍需预检查及 Start。实测与自动测试无需 API key。

自适应运行要求显式的 `adaptive.simulation_approved: true`；`adaptive-demo` 命令代表批准本地模拟闭环。范围和分辨率的选择、已批准范围内的后续模拟扫描自动执行。真实仪器不在本次功能范围内，未增加任何真实驱动、仪器发现或硬件控制路径；故障恢复仍需操作者显式 reconcile。GitHub Actions 自动运行单元测试、Ruff 和三次 TCP 自适应验收。
