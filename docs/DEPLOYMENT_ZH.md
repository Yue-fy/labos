# LabOS 中文部署指南

## 交付文件

- `LabOS-Central-0.1.0.zip`：中央服务、UI、CLI、固定依赖、部署文档及启动脚本；中央需要 Python 3.11+。如构建了 Windows 运行时，包内 `delivery/windows-x64-runtime.zip` 可用于生成 PC 包。
- `LabOS-Agent-0.1.0.zip`：通用 Agent 源码包，需要 Python 3.11+ 或离线 wheelhouse。
- `LabOS-Agent-Windows-x64-0.1.0.zip`：Windows 10/11 x64 便携模板，含 Python 和 Agent 依赖，无需安装 Python；**无真实凭证**。
- `SHA256SUMS`：交付文件校验值。
- 由 `labos bundle` 生成的 `pc-a.zip` / `pc-b.zip`：配置好的单 PC 交付包，只带该 PC 的凭证。可加入便携 Windows 运行时。

默认仅模拟仪器。目标 PC 信息确定后再生成部署凭证和替换受审查的真实驱动。

## 1. 准备中央服务器

源代码开发目录可使用 README 中的 uv 安装。解压后的 Linux 中央包：

```bash
bash install.sh central
export PYTHONPATH="$PWD/src"
.venv/bin/python -m labos init --directory deployments/lab-01 \
  --server-url http://192.168.1.10:8000 --allow-http --host 0.0.0.0
```

替换示例地址为 PC 能访问的实际 LAN/VPN 地址。`--host 0.0.0.0` 仅决定监听地址；`--server-url` 是下发给 PC 的访问地址；二者不是同一参数。不能在远程 PC 使用 `127.0.0.1`。

默认绑定 loopback，避免未选定网络时暴露服务。真实网络部署推荐 HTTPS，或者受控加密 VPN 内的显式 HTTP。详细配置见 NETWORK_ZH.md。

Windows 中央包使用 `Install.ps1 -Role central`，运行 `.\.venv\Scripts\python.exe -m labos` 时先将 `$env:PYTHONPATH` 设置为包内 `src` 的绝对路径。

`init` 随机生成独立凭证，不覆盖既有配置。中央的 `config.yaml` 包含全部 Agent 凭证，必须仅保留在中央。操作凭证在 `central/operator.token`。Unix 自动限制文件权限；Windows 请将部署目录放在操作者专属目录，按实验室 IT 要求限制 ACL。

## 2. 生成单 PC 包

```bash
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-a/config.yaml \
  --windows-runtime delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-a.zip
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-b/config.yaml \
  --windows-runtime delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-b.zip
```

从源码目录执行时运行时路径为 `dist/delivery/windows-x64-runtime.zip`。不加入运行时也能生成包，但目标 PC 要先安装依赖。不要共享同一配置给多个 PC；每个 Agent ID 和凭证只对应一个 PC。

将对应 ZIP 放入 Windows PC 的独立目录，比如 `C:\LabOS\pc-a`，保持 `config.yaml`、`src`、`python` 和启动脚本的相对位置。

## 3. Windows PC 启动

便携包解压后：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Doctor.ps1
```

诊断成功后双击 `Start-Agent.cmd`。脚本使用独立运行时，不依赖全局 PATH，不更改 SSH、防火墙或系统执行策略。`ExecutionPolicy Bypass` 只用于当前脚本进程；受组织策略限制时由 IT 处理。

不带便携解释器的源码包需 Python 3.11+，`Install.ps1` 在本目录创建 `.venv` 并安装锁定依赖。有离线 wheelhouse 时传 `-Wheelhouse C:\LabOS\wheelhouse`。

### 自动启动

先手动验证运行，再注册任务：

```powershell
# 当前用户登录时启动；只创建 LabOS 任务
.\Register-Startup.ps1 -TaskName LabOS-PC-A
# 无需登录的开机启动；需管理员 PowerShell，使用 SYSTEM 身份
.\Register-Startup.ps1 -TaskName LabOS-PC-A -AtStartup
```

启动任务与手动 Agent 不要同时运行；本地目录锁和中央会话校验会阻止重复实例。SYSTEM 与交互用户的网络代理、驱动访问权限可能不同，必须验证；厂商 SDK 若要求交互桌面，应使用登录启动。任务不覆盖同名已有任务。卸载：`Unregister-ScheduledTask -TaskName LabOS-PC-A`。

日志：`data/logs/service.log`。原始光谱：`data/cache/*.json`。不要在实验中清理数据目录或重建配置。

## 4. 首次模拟实验

中央启动：

```bash
.venv/bin/python -m labos central --config deployments/lab-01/central/config.yaml
```

打开中央 URL，粘贴 operator.token 内容，确认 PC-A、PC-B 和三个模拟仪器在线。填写样品和扫描参数，检查实验准备，核对参数，再点击 Start。支持点间暂停/继续、停止、数据预览、HDF5 下载。

计划支持包含终点的对齐网格；500–700 nm 步长 10、0–180° 步长 10，共 399 点。预计曝光时间只显示下界，不虚构总时长。转台角度当前是机械角度；真实偏振角转换须根据装置校准。

## 5. 故障与恢复

- 短暂断网：Agent 重连并重传本地数据。命令超时则实验 FAILED，未知动作不自动重做。
- PC 重启：已完成结果从日志重报；STARTED 命令变为 UNKNOWN，不自动执行第二次。
- 中央重启：活动实验变为 INTERRUPTED，设备占用保留。待 PC 在线后点击“核对并释放设备”，系统请求本地安全状态并确认结果。
- 安全状态无法确认：实验保留设备占用。恢复连接和本地问题后再核对，不能通过删除数据库释放。
- watchdog 故障会持久保存；网络恢复后普通命令仍被拒绝，中央确认本地安全状态后解除。旧实验恢复操作会检查设备是否被新实验占用。
- 暂停：当前完整测量点结束后关闭模拟光源，再进入 PAUSED。继续会重启已批准的模拟光源设置。
- 停止：取消后续普通任务，通知本地取消当前动作，再请求安全状态；已保存原始数据保留。

每次运行的计划、装置、预检查、命令和数据均有 ID 关联。Agent 的本地文件不自动删除。未成功同步的数据继续保留；重传相同哈希的数据不会生成重复点。部分实验也能导出 HDF5。

## 6. 验证范围

Linux 上执行单元/集成测试和三进程 TCP 模拟验收；Windows 便携文件及 wheel 完整性被检查。没有 Windows 实机或真实仪器，因此不宣称 Windows SDK/硬件验证已通过。目标 PC 上请运行 Doctor、短扫描、停止/断网和开机任务验收。
