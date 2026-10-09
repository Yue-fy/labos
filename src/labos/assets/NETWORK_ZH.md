# 网络交互方案：不依赖 SSH

## 通信方向

```text
Windows PC Agent ──主动 HTTP(S) 请求──> 中央服务器
   register / heartbeat / poll / results / artifacts
中央服务器在 poll 响应中返回该 PC 的命令
```

Windows PC 不启动入站 HTTP 服务，不需要开放 22/8000 等入站端口。SSH 可作为可选维护渠道，但不参与实验运行。PC 可以被 NAT 或入站防火墙保护；前提是它能出站访问中央地址。

默认任务轮询 0.3 秒、独立心跳 2 秒、中央离线判断 10 秒、本地 watchdog 15 秒。心跳与 watchdog 分开运行；网络请求阻塞不应阻塞本地监控。失联后取消活动动作并请求本地安全状态。重连退避 1→2→4→8→15 秒，附带抖动。服务器端命令超时默认 20 秒，不自动重发已派发操作。

## 方案 A：专用 LAN

最简单的初始部署：中央与 PC 位于允许互访的 Ethernet/VLAN。中央监听 `0.0.0.0:8000`，PC 配置中央实际 IP，例如 `http://192.168.1.10:8000`。配置显式 `allow_insecure_http: true`，仅用于受信 LAN 或加密 VPN。

IT 只需允许这些 PC 到中央 TCP 8000，中央允许相应来源；PC 入站规则无需改变。Ping 被禁用不等于 HTTP 不通，以 Doctor 的 HTTP 和认证结果为准。相同 Wi-Fi、SSH 不通、ICMP 不通都不能单独证明实验通信不通。

## 方案 B：跨 VLAN/楼宇，经专用 VPN

可采用组织管理的 WireGuard 或被批准的 overlay VPN。PC 和中央使用可路由 VPN 地址，通信仍为出站 HTTP(S)。需要处理 VPN 路由与 ACL；安装或加入 VPN 不由此程序自动执行。若 PC 被禁止安装 VPN，采用方案 C 或由 IT 配置路由。

不要依赖实验室 PC 之间互连；所有调度都经中央。VPN 并不会绕过组织网络政策或阻止的出站流量。

## 方案 C：中央 HTTPS 入口，PC 仅出站 TCP 443

在允许访问中央域名的情况下，将中央服务放在 HTTPS 反向代理之后。中央本体保持 `127.0.0.1:8000`，代理对外提供受信证书。例如 Caddy 配置模板：

```caddyfile
labos.example.org {
    request_body {
        max_size 2MB
    }
    reverse_proxy 127.0.0.1:8000
}
```

模板域名需替换并满足 DNS、证书签发和组织策略。TLS/反向代理部署由操作者或 IT 完成；本项目未申请域名、证书或开放公网。正式 PC 设置 `server_url: https://labos.example.org`，无需 allow_insecure_http。

机构自签/内部 CA：将 CA 文件放入 Agent 包，配置 `ca_file: central-ca.pem`，bundle 自动复制。始终验证 HTTPS 证书，没有 `verify=False` 配置。

代理网络：在 Agent 配置中显式填写 `proxy_url`，如 `http://proxy.example.org:8080`。不默认继承系统 HTTP_PROXY 等变量，避免仪器网络流量意外经过未知代理。若代理含认证信息，配置文件与 ZIP 同样按凭证保护。默认日志不输出带凭证的 HTTP 异常 URL。

## 认证与操作边界

每台 PC 独立 Bearer token；只能访问自己的 Agent API 和已登记仪器。操作凭证与 PC 凭证不同。Agent 注册不能变更中央仪器归属或限制。进程 boot_id 隔离旧会话，双实例拒绝；中央单进程和本地目录锁约束执行权。

公网场景需由 IT 结合来源限制、TLS、限流和凭证轮换进行部署评估。本版没有企业 SSO、RBAC 多用户管理、自动凭证轮换或完整高可用能力。

## PC 诊断顺序

先运行 `Doctor.ps1`：检查地址可达、TLS、LabOS 服务身份，以及该 PC 凭证。这个检查只读，不注册或抢占正在运行 Agent 的会话。

网络不通时，在 Windows PowerShell 使用实际中央地址：

```powershell
Resolve-DnsName labos.example.org
Test-NetConnection labos.example.org -Port 443
```

- DNS 失败：地址或 DNS/VPN 配置问题。
- TCP 失败：路由、中央监听、ACL、代理或出站限制问题；无需先修 SSH。
- TLS 失败：证书域名、CA 或时间设置问题。
- 401/403：PC 配置错误、凭证不匹配或用错 Agent ID。
- 409 注册冲突：已有同 ID 活跃进程；关闭重复实例，或等待旧会话离线。
- 连接成功但仪器离线：查看本地日志、模拟配置；真实仪器后续再查 USB/SDK。

如果 PC 连出站 HTTPS 和 VPN 都被阻止，需要 IT 提供允许的通信路径；更换软件协议不能凭空恢复网络连通性。

## 实验数据与恢复

光谱 JSON 先本地原子保存并 fsync，再上传中央。中央检查 SHA-256、大小、有限数值、命令来源和测量点唯一性。原始数据与上传结果分开记录。上传响应丢失可重传；物理命令响应丢失不能盲目重发。

HTTP 只负责慢控制；没有微秒/纳秒同步保证，快速同步必须由未来硬件触发适配实现。
