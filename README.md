# LabOS MVP

中央规划、本地执行、可追溯数据。首版支持一台中央服务器、两台主动连接服务器的 Windows/Linux Agent 和三类**模拟仪器**。

已经实现：独立凭证、会话隔离、预检查、资源独占、扫描、暂停/继续/停止、UNKNOWN 结果处理、本地 watchdog、数据缓存重传、HDF5 导出、中文控制台、可选 OpenAI 计划草稿。SSH 不是运行依赖。

v0.2 新增：过载/阈值资格检查、拒绝数据留存、计划/配置指纹、已核对资料与旧测试代码检索、带来源的草稿和版本化实验复盘。详见 [QUANTA 改进与操作说明](docs/QUANTA_IMPROVEMENTS_ZH.md)。

系统能力展示：跨 PC 的非线性 Hall 与 BVPE 实验场景，22 页全英文技术版：[PowerPoint](docs/presentations/LabOS_NLH_BVPE/English/LabOS_Technical_Overview_EN.pptx) / [PDF](docs/presentations/LabOS_NLH_BVPE/English/LabOS_Technical_Overview_EN.pdf) / [完整交付包与独立矢量图](docs/presentations/LabOS_NLH_BVPE/English/README.md)。

独立的 [LabOS 系统架构图](docs/presentations/LabOS_NLH_BVPE/System_Architecture/README.md)：一台中央服务器、知识/记忆、科学 Agent 与子 Agent、Skill 库、MCP 工具接口、云端/本地模型切换、执行协调器与通用 PC 群。用少量 PC 符号表示任意规模，不固定分配科研功能；提供英文 PDF、SVG、可编辑 PPT 和高清 PNG。

报告讲解使用 [中英双语架构讲稿](docs/presentations/LabOS_NLH_BVPE/System_Architecture/LabOS_Architecture_Presentation_ZH_EN.md)，含完整中英文讲述、实验示例和常见问答。

运行流程另见 [输运闭环流程图与中英讲稿](docs/presentations/LabOS_NLH_BVPE/Transport_Closed_Loop/README.md)，详细展开通信、自主校准、质量反馈、阶段调整与计划中的理论计算耦合。

真实仪器驱动尚未启用；型号、SDK、连接方式和装置验证齐备后再接入。模拟数据均有显式标记。

## 开发环境与本机验收

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[central,ai,dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m labos demo --directory runtime/demo-01
# 完整 399 点实验；使用新的输出目录
.venv/bin/python -m labos demo --directory runtime/full-demo-01 --full
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
