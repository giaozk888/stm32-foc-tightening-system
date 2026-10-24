# 当前设置 Git 快照：2026-10-24

保存当前工作区的固件、候选配置、离线测试、板测说明及 Simulink 源码。此次仅进行 Git 归档，不烧录、不复位、不启动电机，也不把候选参数提升到物理 B。既有 A/B 源码差异均作为历史工作区状态保存。

## 选用的正常候选 A

构建预设：`TighteningDob025Contact20Observe10Candidate`，定义见 `foc2_app_a/CMakePresets.json`。不同诊断预设可覆盖参数，不能把头文件中的通用默认值当作所有预设的最终值。

|设置|选用值|
|---|---|
|FOC 频率|20 kHz|
|RUNDOWN 目标|240 rpm|
|总 Iq 限幅|±0.50 A|
|正常独立超速 / 行程上限|300 rpm / 20000°|
|RUNDOWN 超时 / 会话限时|8 s / 12 s|
|CONTACT 速度门槛|20 rpm|
|DOB 观察下限 / 新鲜反馈速度下限|10 rpm / 20 rpm|
|加速度前馈 Ka|0.000046875 A/(rpm/s)|
|S-curve 最大加速度 / jerk|200 rpm/s / 1000 rpm/s²|
|库仑摩擦补偿 / 零速死区|0.105 A / 2 rpm|
|BEMF 所用磁链|0.00034866 Wb|
|dq 交叉解耦|OFF|
|DOB 反馈增益|0.25|
|DOB 补偿限幅|min(0.025 A, 0.05 × Iq limit)|
|DOB 补偿斜率|0.25 A/s|
|反馈新鲜 / 保持 / 失效|2 ms / 5 ms / 20 ms|
|DOB 专用 Id/Iq 跳变门槛|200 mA，LPF 前隔离及一致性确认|
|Id 质量幅值 / 持续判定|60 mA / 20 ms|

电流 PI、速度 PI、采样、角度链、一周期 PWM pipeline、CUR_CONFIRM、CURRENT_INVALID、独立保护及 IRQ 配置以保存的代码为准，本次归档未修改这些算法。参数辨识候选仍保留质量限定，不能将用户选用的 Rs/Ld/Lq 当作仪器确认的电机物理参数。

DOB 当前名义模型采用机械 rad/s：

```text
J/Kt = 0.0003782906586526162 A*s²/rad
B/Kt = 0.0015676864325576986 A*s/rad
Ic/Kt = 0.11945168237076952 A
current bias = 0.0005496600325149542 A
observer bandwidth = 12.566370614359172 rad/s
```

## 最新实测与仿真边界

最新空载对照见 [各十轮实测结果](dob-gain-ab-twenty-results-20261023.md)：DOB 0.25 / 0.5 各十轮，240 rpm。0.5 未显示完整加速和匀速指标的稳定收益，继续选用 0.25。空载 RUNDOWN_TIMEOUT 不表示拧紧成功；仿真中的负载改善也不表示真实工件性能已验证。

本地暂存的 A 为 `DobGainAbCandidate` 诊断镜像，默认反馈 OFF，可受控选择 0.25/0.5；与上述正常候选不同。其 BIN SHA256：`b63e5bfb9662ee808f2424f75512de3ef4135ad0f9fd2365722f2c6f28357535`。最新人工确认 12 V 关闭，恢复原 B 启动选择的记录为本地 `tmp/dob-gain-ab-restore-1792763799510887400.json`：PASS、无电机命令、MCU halted、输出关闭。

## 文件及复现

- 保存固件公共模块、A/B 构建配置、测试、主机工具、阶段记录、Simulink 构建源码、五次实测短窗输入和小型指标汇总。
- 原始 Flash/RAM、备份、逐次 MAT/CSV 大型轨迹、Simulink/SDI 缓存、构建产物、聊天附件和个人目录留在本机。部分历史文档指向 `tmp/` 的链接仅在原工作区可用。
- `simulation/dob_simulink/README.md` 及 `real_five/README.md` 说明模型重建与运行方法；需要 MATLAB/Simulink 和本机编译工具链，路径可能需要调整。未归档的逐次原始轨迹需要重新运行才能生成，不能仅凭汇总表执行逐帧审计。
- 克隆后先 `git submodule update --init --recursive`，再按项目说明构建。Pigweed 子模块固定版本未变；本机 `pw_build/pigweed.cmake` 的 Git 规范化内容与子模块 HEAD 相同，仅有换行状态差异，不提交新子模块版本。
- 正常配置与诊断工具均不会因 Git 上传自动烧录或运行。任何后续实机试验仍需确认实际供电和机械状态。
