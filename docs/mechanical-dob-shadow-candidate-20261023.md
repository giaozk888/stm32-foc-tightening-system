# 联合机械模型 → candidate A DOB shadow

后续首轮人工板测已经完成，实测结果及B1043恢复凭据见
`docs/mechanical-dob-shadow-board-20261023.md`。本文件保留的是开发候选时的构建与状态记录；
板测未启用DOB反馈，有效覆盖率尚未达标。

## 范围与当前实板状态

用户回复“关了，按照图继续下一步”后，已先恢复原 B 启动选择。
恢复凭据：`tmp/mechanical-ident-restore-1792713878339933000.json` PASS。
原 B、boot、配置及私有区不变，metadata generation=1039、active=B、pending=none；
最终 VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted、motor_commands=0、B application not run=true。

本轮随后只做离线开发/构建。**新 DOB A 未写板、未激活、未运行，未启用扰动补偿**。
板上 A 仍是上一轮反向辨识镜像，不是本文件描述的新候选。

按图使用电流归一化机械模型，不假造绝对 J、B、Kt：

`Iq = a*alpha + b*omega + Ic*sign(omega) + bias + disturbance_A`

omega 为有符号机械 rad/s，alpha 为机械 rad/s²，Iq 为 dq A。
参数来自 `tmp/mechanical-bidirectional-fit-1792713255600021200.json`，
正反向各九次，共 18 次独立采集，1956 个主拟合窗口；
64/128 ms 下 a 变化 -1.443620%，18 次留出复核通过。
完整证据及模型局限见 `docs/mechanical-bidirectional-results-20261023.md`。

|参数|本候选采用的联合拟合值|单位|
|---|---:|---|
|a = J/Kt|0.0003782906586526162|A·s²/rad|
|b = B/Kt|0.0015676864325576986|A·s/rad|
|Ic = Tc/Kt|0.11945168237076952|A|
|bias|0.0005496600325149542|A|

参数以 float 常量保存，表中为拟合源精度。bias 是共同模型截距，不是独立测出的 ADC 零点。
不把正向截距 0.120735 A 直接当作库仑摩擦电流。
本轮不改现用摩擦前馈 0.105 A，不用新模型自动重标定它；估算器从**实测电流**扣除模型项，
不是把现有前馈再加一遍。

## 观察器与控制隔离

`Q(s)=g/(s+g)`，`g=12.566370614359172 rad/s`（2 Hz）。

`D_A = Q(s)[Iq_matched - b*omega - Ic*sign(omega) - bias] - a*s*Q(s)*omega`

同一离散极点实现两条 Q 支路，滤波状态实现微分；不裸差分 noisy speed。
Iq 单独以 20 ms 一阶低通匹配现有 20 ms 速度滤波，**不改控制反馈电流或速度滤波**。
至少 20 rpm、经过五个时间常数（约 398 ms）后才允许观察值有效。
低速、坏数据、异常时序、饱和或模型域不符均让观察值无效、复位并重新预热。
这些只是 **DOB 证据准入，不是新增电机停机保护**。

- 唯一 writer 为原约 1 kHz MotorControlTask；在真实 encoder ACK、外环完成确认后执行。
- 使用原相干 ADC pair-read 的 Iq/Id/序号/source/publish 时间，与同次 encoder 时间/速度。
- 未改 ADC IRQ、PI、角度链、PWM pipeline、CUR_CONFIRM、CURRENT_INVALID、保护或 IRQ priority。
- 没有 Iq/PI/PWM、watchdog ACK 或持久参数写接口，没有“DOB ON”命令；永远 `FEEDBACK=0`。
- STOP/fault 后 task 观察器冻结，不自动重新 arm；ISR 原关断路径不变，不依赖 DOB 任务运行。
- UART 另核对当前 session/故障/样本年龄，旧历史不能显示成 LIVE/VALID。
- 2 Hz、20 rpm、filtered abs Id≤0.05 A 为本候选的观测带宽/模型证据配置，不提高安全阈值。
- `D_A` 是电流等效剩余负载。正向额外阻力为正，反向额外阻力通常为负；不是已标定 Nm。

保留 Ka=**0.000046875 A/(rpm/s)**、BEMF ψ=0.00034866 Wb、原 PI/S-curve/前馈配置。
继承当前诊断 A 的 Iq±0.50 A、1.60 V、1000 rpm 独立超速、30000° 行程、
5 s 驱动、10.5 s task closure、12 s lease、2 ms 外环与 2.5 ms encoder control 保护。
本轮没有扩大任何限幅/阈值；这些诊断配置不写入正式 B。

## 记录与只读协议

记录：encoder sample_us、ADC seq/source_us/published_us、omega_rad_s、
Iq、匹配低通 Iq、Id、disturbance_A、status、valid。
另有全 session observations/valid/rejected、有效观察值峰值及正负方向均值、观察计算 wall max_us。

RAM ring 为 16 个 **间隔至少 64 ms 的瞬时快照**，不是辨识用的 64 ms 积分 bin；
保存末尾约 1 s，不能据此宣称记录了每个 1 kHz 点。
全 session 均值为有效观察次数均值，不冒充逐时间权重平均。
REJECT 计质量失败，高 Id 等不准入；低速/预热不计入 REJECT，但明确标为无效。
max_compute_us 独立更新，为包含 IRQ 抢占的最大 wall time，不是每帧原子快照的一部分。

只读命令（普通请求号前缀沿用原协议）：

```
MOTOR TEST MECH DIRECTION
MOTOR TEST MECH DOB MODEL
MOTOR TEST MECH DOB
MOTOR TEST MECH DOB ADC
MOTOR TEST MECH DOB STATS
```

数值、ADC 时间戳、统计分行查询，适配真实 192-byte 协议回复缓冲区；
没有扩大 buffer/线程栈。单位明确为 *_UA（µA）、*_MRAD_S（mrad/s），MODEL 的 J/B 为 nA 归一化单位。
拆分查询可能跨 task 更新：需要严格同帧分析时，以 US/SEQ 或停机后的 RAM 为准。
BUSY=1 表示 seqlock 未取得相干读，不能重用旧值冒充新值。
解码工具 `tools/mechanical_dob_report.py` 校验同 session ELF/BIN/Flash/RAM hash、
原关断/保护闭合、符号地址/ABI、冻结状态、ring 顺序、时间回绕、NaN 和有效性。
历史 VALID 仅表示采样当时有效，离线 `live=false`、`feedback_enabled=false` 固定。

## 修改文件

新增：

- `firmware_common/mechanical_dob_monitor.h/.c`
- `firmware_common/mechanical_dob_binding.inc`
- `tools/mechanical_dob_report.py`
- `tests/test_mechanical_dob_monitor.py`
- `tests/test_mechanical_dob_report.py`
- 本文档

接入/隔离配置：

- `foc2_app_a/Core/Src/main.c`：task-only 全局 monitor 与 post-ACK 观察尾部。
- `firmware_common/protected_closed_loop.inc`：只读协议、task lifecycle。
- `firmware_common/friction_calibration.h`：新 shadow profile 仅接受显式 ±600 rpm。
- `firmware_common/friction_calibration_binding.inc`：只读命令分派与诊断身份。
- `foc2_app_a/CMakeLists.txt`、`foc2_app_a/CMakePresets.json`：独立默认关闭的 `MechanicalDobShadowCandidate`。
- `docs/mechanical-bidirectional-results-20261023.md`：补记本轮恢复 B 凭据。

正式 B 源码/配置本轮未改，原 shadow 数学核心也未改。

## 构建/离线验证

|构建|Flash B|RAM B|RAM 剩余 B|
|---|---:|---:|---:|
|MechanicalDobShadowCandidate A|213620|130400|608|
|MechanicalReviewB 原本地 B 配置复编|228300|128792|2216|

**A 静态 RAM 余量很紧**：没有缩小 heap 或线程栈。编译通过不等于运行栈余量/实时性已验收。
本地 B 复编不是重刷实板原 B；实板 B 仍为原 227964 B / CRC 627317606。

- A BIN SHA256 `74d53cf4e47743ccfa8bfbe5ca73ed4d58dcc0332ca59b785bfe8b54bb84e770`。
- A ELF SHA256 `6ab8d8f68708e9b65dec79a8bac3a1319080068f506823d7586bb3dd63003654`。
- 本地 B BIN SHA256 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，与修改前逐位一致。
- A/B 编译通过，没有新增 warning 类型；历史 unused / RWX warning 仍存在。
- 241 项相关离线回归通过，日志 `tmp/mechanical-dob-shadow-regressions-final.log`。
- 新增 8 项：实际 C 在 -Os/-O2 下匹配滤波、匀加速/正负扰动、质量失效与预热、
  STOP/fault 冻结、无自动重启、时间/序号回绕、只读协议真实 buffer 极值、RAM ABI/来源与保护校验。
- 对照原 readiness candidate，实际预处理的 PI、IRQ、power stage、angle、PWM、admission、FSM 函数未变；
  除 lifecycle 前缀/非控制观察尾部外 TaskService 与 Flush 不变，关键独立对象逐位相同。
- 合成 ±0.02 A 扰动只是数学/集成测试，不是实机扰动性能或负载测试结果。

## 下一轮人工板测顺序（本轮未执行）

1. 12 V 关闭、MCU 供电，转轴解锁、空载固定并防护，12 V/限流0.5 A，现场可立即断电。
   只更新非活动 A、完整回读并核对本候选 hash，保留原 B。旧正/反向 runner 有严格镜像白名单，
   **不能直接复用旧 stage/run 凭据去激活这个新镜像**，需先适配并测试新 wrapper。
2. 人工确认上电无报警后，校准、功率关闭预检；确认身份 SHADOW=1/FEEDBACK=0、MODEL 与 LIMITS。
   检查 FOC max/deadline miss/CCR late、外环耗时与线程最小栈余量；不达标不进入运动。
3. 第一段只执行显式 `MOTOR TEST MECH RUN POS 600`，沿用原轨迹及关断路径。
   观察连续预热后 VALID 覆盖率、D_A 均值/峰值/噪声、Id/饱和与质量原因、max_compute_us。
   不能把旧数据或无效点平均当成结果；不手碰/手持工具阻挡旋转轴。
4. 停机保存同 session 完整 Flash/RAM/ELF/receipt，确认 SD/MOE/CCER 关断。
   降电、恢复 B 后审查第一段，再准备独立 NEG 600 段；不自动重试或自动反馈。
5. 对比正负方向模型残差及延迟，确认现有摩擦/前馈没有被重复补偿。
   要做已知外载扰动，应另外设计固定负载夹具/参考测量；空载观察不能验收真实 Nm 或闭环抗扰。
6. shadow 的实时性/有效性/方向通过后，再单独设计 DOB 限幅、总 Iq anti-windup、
   启停/低速无扰切换和反馈验收。本轮不向 Iq 求和，不承诺速度或抗扰性能改善。

**DOB 观察候选已就绪，等待人工空载板测。**
