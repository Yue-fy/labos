# LabOS 跨 PC 协同实验：非线性 Hall 与 BVPE

这是一套 **19 页、16:9、中文系统能力展示**，适合约 15–20 分钟组会或方案交流。基于用户提供并确认的 PC A / PC B 装置清单，讲解中央 Agent、多 PC 协同、物理信号链与联合测量流程。所有示意图均为本系统重新绘制。

- `LabOS_NLH_BVPE_System.pptx`：文字、框图与连线均可编辑，含逐页演讲者备注。
- `LabOS_NLH_BVPE_System.pdf`：相同内容和布局，中文与科学符号字体已嵌入，文字可检索。
- `讲解稿.md`：与幻灯片逐页对应的讲解。
- `LabOS_slides_overview.png`：全部页面预览。
- `build_presentation.py`、`slides_scene.json`：可复现的矢量排版源文件。
- `QA_REPORT.json`、`SHA256SUMS`：交付检查与摘要。

图示设备归属：PC A 为 SuperK 与红外光谱仪；PC B 为 attoDRY、Vxx/Vxy 两台输运锁相、chopper、BVPE 锁相、PD、2400、730 nm 激光器、CLD1000、电控偏振片或四分之一波片。电激励使用锁相输出与串联电阻。

主线：研究问题 → 总体架构 → 设备与光/电/参考链路 → 网络与时序 → 实验准备 → Hall 与 BVPE 测量阶段 → 联合任务 → 数据质量与证据 → 使用与扩展。

演示以完整应用场景说明系统能力，不包含材料实测曲线或接入待办。光源、参考通道、读出方式与参数按实验配置表达。PDF 与 PPT 由同一份矢量布局生成；PPT 中文字体设为 Windows 常见的 Microsoft YaHei，PDF 嵌入字体，跨平台替换字体可能使字形略有差异。

## 再生成

Python 依赖：`python-pptx`、`reportlab`、`fonttools`；预览/检查另外使用 `pymupdf` 和 `Pillow`。脚本顶部的字体路径可按本机字体修改。

```bash
python build_presentation.py
python verify_presentation.py
```

参考论文与 DOI 列于第 19 页和讲解稿。系统框架表达参考 QUANTA 的分层结构，图示的设备、场景与叙述以 LabOS 为主体。
