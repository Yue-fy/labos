# LabOS 0.1.0 交付与验收记录

日期：2026-10-09（Europe/Helsinki）。项目：`/home/fangy4/work/projects/LabOS`。

## 已交付

中央服务、中文控制台、固定扫描运行器、两个出站 Agent、三类模拟仪器、独立凭证与会话、设备独占、实验预检查、暂停/继续/停止、显式恢复、本地数据与命令日志、SHA-256 校验上传、HDF5、可选 OpenAI 草稿接口、Windows/Linux 启动与诊断脚本、Windows x64 便携运行时和角色 ZIP。

发布包位于 `dist/`；每个角色通用包不带真实部署凭证。中央 `init` 和 `bundle --windows-runtime` 可生成单 PC 包，只含该 PC 的配置与凭证。

## 验证结果

| 验收 | 结果 |
|---|---|
| pytest 自动测试 | 44 项通过 |
| Ruff | 通过 |
| Bash 启动/安装脚本语法 | 通过 |
| 三个独立 OS 进程、真实 loopback TCP、两个 Agent | 399 点扫描完成；HDF5 counts 为 399 × 128 |
| 最终中央 ZIP 解压到含空格目录 | 9 点 TCP 扫描完成，HDF5 校验通过 |
| Chromium 控制台流程 | 登录 → 预检查 → Start → 完成 → HDF5 下载 → 清除凭证通过，无 JavaScript 错误 |
| 真实 TCP 故障恢复 | 关闭运行中的中央服务 → 本地 watchdog 故障持久化 → 重启中央 → 数据保留且实验 INTERRUPTED → 显式恢复 → 新的 2 点实验完成 |
| Windows 便携运行时 | Python 3.14.8 官方 SHA-256 匹配，12 个 Windows binary/pure wheels，ZIP 完整性通过 |
| 发布 ZIP | 文件名无重复、路径安全、通用包无部署凭证；源码及 wheel 包含最终修复 |

实际执行环境为 Linux + Python 3.12.3。Windows Python 来源与每个 wheel 的哈希保存在便携包 `python/RUNTIME_PROVENANCE.json`。Windows 解释器、PowerShell、任务计划程序、厂商 SDK 尚未在目标 PC 上执行，不能将交叉构建视为 Windows 实机通过。

OpenAI 接口使用 mock 验证草稿与拒绝路径；未调用收费 API，真实模型响应待操作者配置后验证。真实 LAN/VPN/TLS/代理、域名及 PC 防火墙尚未部署；提供了配置与诊断方案。所有实验数据是模拟数据。

## 独立代码审查

独立只读审查发现两项 Important 问题，无 Critical。以下问题均先用回归测试复现失败，再修复并运行全套测试：

1. 旧失败实验恢复可能操作新实验的设备：恢复时原子检查/取得全部资源，命令入队再次验证归属。
2. watchdog 关光后可能继续扫描：故障持久记录到 PC SQLite，后续普通动作拒绝；恢复需确认新的安全关闭命令；中央采集前验证功率与快门。

修复后的完整扫描、浏览器流程、故障恢复、解压包验收均重新通过。未发现需要暂缓的审查 Minor。

## 实施决定与剩余范围

- 按用户指定空目录建立独立项目并直接执行；保留本地 `implementation/mvp` 分支，无远程仓库、发布或合并动作。
- 首批按 Windows x64 准备；PC 型号、Windows 版本、设备与 SDK 尚未给定，因此只启用模拟驱动。后续需要目标 PC 诊断和只读/小范围硬件验证。
- 以出站 HTTP(S) 取代 SSH 运行依赖。仍需要 PC 到中央的真实网络路径；组织禁止出站时须由 IT 提供连通性。
- 暂不引入通用 YAML 引擎、自动生产驱动、高可用执行器、企业 RBAC、快速硬件同步。交付的明确范围是一套可追踪、可恢复、可部署的模拟 MVP。

## 复现命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/python -m labos demo --directory runtime/new-full-acceptance --full
.venv/bin/python scripts/network_fault_acceptance.py
.venv/bin/python scripts/browser_acceptance.py  # 需额外安装 playwright 和 Chromium
```

每次 `demo` 使用新的目录，避免覆盖配置、凭证和实验数据。可查 `dist/validation/` 中保存的验收 JSON、控制台截图与 399 点 HDF5 示例。
