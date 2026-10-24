# AF1：A-only 加速度前馈候选

本轮只做代码审查、离线测试和构建。未刷板、未复位、未修改启动选择、未启动电机。正式 B 及原 SC1 tokenized 镜像保持不变；离线结果不代表真实误差或时序已经改善。

## 接入与公式

`FSM → ControlIntent → 已有 S-curve → 原 speed PI + acceleration FF + 合并 AW/限幅 → 原 current PI → SVPWM → 原一拍 PWM pipeline`

只在 `FOC_EncoderSpeedUpdate` 的 SPEED 分支使用已有 `speed_scurve.acceleration_rpm_s`，不进入 POSITION/IQ 分支或 20 kHz ADC ISR：

```
iq_ff  = enabled ? Ka * accel_ref : 0
iq_pi  = p_term + admitted_integral
iq_raw = iq_pi + iq_ff
iq_ref = clamp(iq_raw, -iq_limit, iq_limit)
```

anti-windup 对包含 FF 的 tentative raw/ref 判断是否向饱和方向积分；只接纳到 `±iq_limit - iq_ff - p_term` 边界，再重算最终 PI/raw/ref。原强制卸载/退积分不被阻止，最终仍限流。FF OFF、Ka=0 或巡航 accel=0 时调用原 AW helper，保持原输出/积分数值。饱和标志包含输出钳位、边界及发生部分积分接纳的帧，避免浮点舍入使“边界内一个 ULP”漏记饱和尝试；不因此新增控制分支。

Ka 可通过 CMake cache `FOC_ACCEL_FF_KA_A_PER_RPM_S` 配置，编译宏 `SPEED_ACCEL_FF_KA_A_PER_RPM_S`：

- 初值 **0.0001875 A/(rpm/s)**。
- 原 S-curve 加速度最大 200 rpm/s，FF 峰值 **±0.0375 A**，为原 ±0.50 A Iq 上限的 **7.5%**。
- 第一版候选配置拒绝 Ka 大于 0.00025（200 rpm/s 时 50 mA / 10%），不改变现有电流上限或任何保护阈值。
- 未加入速度前馈、摩擦补偿、DOB；PI 增益、S-curve、SB2、SB3 OFF 选择、FOC 数学、IRQ、保护及 A/B 逻辑均未修改。

## 配置及操作接口

A 新增 preset：`Tightening240rpmAccelFfOnCandidate`、`Tightening240rpmAccelFfOffCandidate`。都继承已 tokenized 的 SC1，AW 开启、SB3 关闭、240 rpm / ±0.50 A / 原保护与会话边界不变。功能默认 OFF，仅新 preset 开启；不把功能加入 B。

同一个镜像也支持 RAM-only 开关，UART：

```
MOTOR TEST FF OFF
MOTOR TEST FF ON
MOTOR TEST FF STATUS
MOTOR TEST FF METRICS
MOTOR TEST FF METRICS2
```

ON/OFF 只允许 FSM 空闲、无排队 START/STOP、MODE_IDLE、SD=0、MOE/AOE=0、CCER=0 时切换，检查与更新在任务临界区内完成；格式化在临界区外。开关不启动、不复位 PI、不重装会话、不保存 KVS。ON/OFF 或新 SPEED 段入口重置统计；退出 SPEED 不抹掉上一段结果。重新校准/控制器复位仍会清除 RAM 统计，因此先保存结果再复位。

## 日志压缩和统计

候选强制 `PW_LOG_TOKENIZED_DEFAULT=ON`，使用此前的官方 token codec 和原 `[PWT]` 传输链。新增日志不是 printf，也不把长格式字符串带入 BIN；字典留在**对应 ELF**，必须匹配运行镜像。固定机器协议回复保持文本兼容，不声称它们也已压缩。

MonitorTask 约 10 Hz 抽取最近一次完整 frame，分两条 token 日志、以 seq 关联：

- `AFF R`：speed_ref、speed_meas、accel_ref、command、FF ON/OFF、时间。
- `AFF C`：iq_pi、iq_ff、iq_raw、iq_ref、speed_integrator、saturation。

32 B 编码缓冲保持不变；真实 codec 的最大 uint32 seq/ms 与浮点往返测试通过，不靠截断挤入一条长消息。没有在 ISR 中格式化/UART；1 kHz owner 只生成二进制 frame/在线聚合，发布 IqRef 后再统计。

`METRICS/METRICS2` 为有效速度更新处（约 1 kHz，按实际 dt 加权）统计，不由 10 Hz 日志估算：

- 最大 `abs(speed_ref-speed_meas)`；ref×accel 正/负时的加速/减速 MAE。
- 参考抵达最终 command 后的最大定向 overshoot。
- 最近 command 段开始到最终目标稳定带首次进入的时间：±max(2 rpm, 5% command)，连续 250 ms；随后离带则重新判定，未建立返回 -1。
- `|IqRef|`、采样 `|Iq|`、积分器峰值；饱和累计时间及最长连续时间。Iq measured peak 为外环采样峰值，不冒充 20 kHz 原码硬过流峰值。
- 未出现的加/减速阶段返回 -1。当前 FSM STOP/故障仍立即关输出，不是 S-curve 减速测试；未采减速时不能报告零减速误差。

`tools/accel_ff_compare.py off.log on.log` 离线比较两次保存的 STATUS、METRICS、METRICS2，生成 ON/OFF/delta。拒绝混合或冲突快照，未观测阶段为 null。它不连接设备、不自动重试/运行。两次目标、负载、电源、限幅、覆盖窗口必须一致，不能只靠工具输出判定因果。

## 修改文件

- `firmware_common/speed_accel_feedforward.h/.c`：合并 AW/限幅及指标聚合。
- `firmware_common/speed_accel_feedforward_binding.inc`：A-only 空闲开关、任务快照和低频报告。
- `firmware_common/speed_accel_feedforward_log.cc`：两条压缩日志。
- `foc2_app_a/Core/Src/main.c`、`CMakeLists.txt`、`CMakePresets.json`：候选接入。
- `firmware_common/protected_closed_loop.inc`：条件编译命令及 `SPEED_CTRL=AF1` 身份。
- `tools/accel_ff_compare.py`。
- `tests/speed_accel_feedforward_host.c`、`speed_accel_feedforward_log_host.cc`、`test_speed_accel_feedforward.py`。
- README 和本文。B 源码/配置本轮未修改。

## 构建与测试

| 构建 | Flash / 229376 B | RAM / 131008 B |
| --- | ---: | ---: |
| A AF1 FF ON | 214900 B | 128976 B |
| A AF1 FF OFF | 214900 B | 128976 B |
| B 原 CommonMode，仅隔离重编译 | 228300 B | 128792 B |

A 剩 14476 B Flash、2032 B 静态链接 RAM（不是任务剩余栈保证），较 tokenized SC1 增加 3400 B Flash/144 B RAM。新模块编译无警告，主程序/链接仍有此前 unused/RWX 警告，无新增 warning/error。

- ON BIN SHA256：`9a7a0c9d57d8017dea55c31687c3ee2a69dac0d969dbac33a07b70eec0cb2642`。
- ON ELF SHA256：`726e57051efdadec67f1cfdf4dbdb99d61e9c743d2fd3927f7c994c9a9890ae9`。
- OFF BIN SHA256：`2c3cb5db78bf9fc6f6f508391f3259cece1f510587beab8933f1a93199714104`。
- B BIN SHA256：`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，与原 B 构建逐字节相同；该编译产物不是声称已替换板上稳定 B。

61 项定向回归和 12 项共享 UART/日志等 CTest 全部通过。覆盖正反加速、反向 FF 释放余量、合并饱和、退积分、OFF 等价、POSITION 不变、空闲切换/排队命令、压缩 codec/ELF、指标及无新增编译警告。预处理冻结函数比较、ADC/IRQ/S-curve 对象逐字节校验保持不变。最终日志见 `tmp/accel-ff-regression-20261020.log`、`tmp/accel-ff-shared-ctest-20261020.log`。不宣称全部历史仓库测试均运行。

## 人工板测步骤（本轮未执行）

1. 后续人工授权并核对现场状态后，仅写非活动 A、完整回读、保留当前 B；用新 AF1 镜像/ELF 和独立收据，不复用旧 SC1 固定 hash 脚本或绕过身份校验。
2. 按原电源/空载固定/全部保护条件，先校准和时序预检；核对 AF1、TOKENIZED=1、Ka 与 FF 峰值。新外环统计/日志有开销，必须重新确认 50 us deadline、CCR late/margin 及任务栈。
3. 输出关闭空闲时选择 FF OFF，执行一次原状态机同配方测试；自然无接触超时仍是预期，不强制 CONTACT。停止后、任何复位前，保存 STATUS、METRICS、METRICS2 及完整日志。
4. 独立准备另一轮、保持同配方/负载/供电/时长，选择 FF ON 后做一次相同测试并保存。开关不能自动恢复 lease 或清除故障；出现保护或预检失败就停止，不自动重试。
5. 使用各自匹配 ELF 解码 `[PWT]`，用比较工具核对最大误差、阶段 MAE、过冲、稳定时间、电流/积分峰值及饱和时长；没有受控减速窗口则减速 MAE 标未测，不能把立即 STOP 当减速。不要据单次差异自动加 Ka。

加速度前馈候选已就绪，等待人工板测

随后人工确认完成[一次FF ON空载实测](accel-ff-fsm-board-20261020.md)：FOC max31.62us、deadline/CCR late=0，FF峰值37.5mA，日志解码生效；但仍局部掉速、未建立稳定时间，无同条件OFF对照，不能宣称改进通过。已关闭12V并恢复原B772，不再运行。
