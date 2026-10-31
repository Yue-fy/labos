# Windows 安装修复：0.2.1

日期：2026-10-31（Europe/Helsinki）。

## 报错原因

0.2.0 的 `Install.ps1` 通过 `python -c` 执行含双引号的 Python 代码。Windows PowerShell 的旧版原生命令传参方式会丢失这些内部引号，使代码截断在 `print(Portable`，出现 `SyntaxError: '(' was never closed`。

已使用 PowerShell 的 Legacy 参数模式运行交付脚本，复现相同错误。相关机制见 [Microsoft 官方参数解析说明](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing#passing-arguments-that-contain-quote-characters)。

## 已修复

- 改为执行独立的 `Check-Runtime.py`，避免内联 Python 的引号问题。
- 检查实际 Agent/CLI 模块、依赖和内存 SQLite，避免仅顶层包可导入却无法启动。
- 安装过程保留 `install.log`；`Install.cmd` 保留真实退出码。
- 无 `config.yaml` 时明确提示先取得中央生成的单 PC 配置；Doctor 也会给出相同方向的提示。

检查文件只验证本地运行环境，不读取凭证，不连接服务器或仪器，不执行参考 Notebook。

## 已解压 0.2.0 的子电脑：使用小补丁

1. 将 `LabOS-Windows-Install-Fix-0.2.1.zip` 复制到 Windows 子电脑。
2. 把其中的 `Install.cmd`、`Install.ps1`、`Check-Runtime.py` 和 `Doctor.ps1` 放入原 Agent 解压目录的根目录，替换同名脚本。
3. 确认它们与原有 `ROLE` 文件、`python` 和 `src` 文件夹位于同一级，再双击 `Install.cmd`。
4. 应看到 `LabOS agent runtime OK`，最后退出码为 `0`。
5. 如果尚无 `config.yaml`，此时显示配置提示是正常结果；取得配置前不用启动 Doctor 或 Agent。

补丁只修复启动脚本，不替换现有 `config.yaml`、`src`、运行时或数据；应用补丁后的应用核心仍是原来的版本。全新部署请使用完整的 `LabOS-Agent-Windows-x64-0.2.1.zip`。

## 如果仍报错

查看同目录的 `install.log`，提供最后一段错误。不要删除或重建已有配置和数据。若连脚本都无法启动，窗口中可能没有生成日志，此时需保留窗口里的系统报错。

## 验证范围

自动回归运行真实 PowerShell 脚本和 Python 检查，覆盖 Legacy 参数模式、含空格/括号/中文的路径、缺失模块、缺失 PC 配置和安装日志。Linux 测试用本机 Python 替代 Windows 可执行文件，不能将其称为 Windows 实机验收。

Windows 原生便携解释器和厂商 SDK 的最终结果仍以目标子电脑复测为准。仓库中的 `scripts/verify_windows_delivery.ps1` 可在 Windows 上验证完整 ZIP；它不启动 Agent 或访问仪器。
