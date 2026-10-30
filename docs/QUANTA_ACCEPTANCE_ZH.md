# LabOS v0.2 验收记录

日期：2026-10-30；执行环境：Linux、Python 3.12、Chromium。全部实验使用模拟仪器。

本次新增质量门控、拒绝数据留存、软件计划/配置指纹、版本化资料检索、来源引用和确定性实验复盘。实现说明见 [操作指南](QUANTA_IMPROVEMENTS_ZH.md)；原 v0.1 验收记录保存在 [ACCEPTANCE_ZH.md](ACCEPTANCE_ZH.md)。

## 已执行

- 单元/API/运行器测试：58 项通过。上游 Starlette/httpx 有一条既有弃用警告。
- Ruff 与 `git diff --check`：通过。
- 三个独立进程、真实 loopback TCP：模拟探测器过载，拒绝首个光谱，有效点数为 0，原始数据与资格原因保留，停光软件读回已确认。
- 拒绝实验仍可导出 HDF5：`raw/counts` 为 `0 × 128`，审计区保留 1 条记录。
- 对复盘建议重新预检查并显式启动另一个实验，较短曝光完成 3 个合格点；来源 ID/摘要与计划关联，两次运行均释放设备。
- 真实 Chromium：资料导入/检索/引用、预检查、手动启动、完成、复盘、合格数据下载、质量拒绝、拒绝数据下载、建议载入后 Start 保持禁用、退出；无 JavaScript 错误。
- 断网/重启回归：运行中关闭中央，本地 watchdog 故障持久化；重启后旧实验 INTERRUPTED 且数据保留；显式恢复后新实验完成 2 点。

完整 399 点、最终交付包解压运行与独立审查结果在完成后补记。

## 不代表的验证

没有在 Windows 实机运行 PowerShell、Python 便携解释器或厂商 SDK；没有连接真实仪器，没有部署真实实验室 LAN/VPN/TLS。模型调用仍用 mock 验证，没有调用收费模型。软件停光读回不是独立物理急停，也不能证明样品无损伤。资格检查仅为当前光学模拟流程的运行有效性检查，不代表精度、稳态或科学机理已确认。

## 实施决定

- 在指定项目目录的改进分支直接执行，没有另开工作树；主分支在审查完成前保留。
- 恢复建议需要新预检查与人工 Start，没有自动重试或自动改变实验边界。
- 没有套用论文的数值阈值到光学装置；SNR、漂移和相关性分析需后续具体实验支持。

复现：`python -m pytest -q`、`python scripts/quality_acceptance.py`、`python scripts/network_fault_acceptance.py`、`python scripts/browser_acceptance.py`。应使用项目虚拟环境；浏览器脚本另需 Playwright 与 Chromium。
