# SC1：AW 开启、SB3 关闭的 S-curve 候选（2026-10-20）

本轮只做软件接入、编译和离线验证。没有刷板、复位、修改启动选择或启动电机；不能把离线轨迹通过等同于真实电机速度/时序通过。

## 接入位置与不变项

新增 A preset `Tightening240rpmScurveCandidate`，继承 `Tightening240rpmAwNoSb3Candidate`（AW0），不是撤销新 AW 的 L00。`FOC_SPEED_SCURVE_CANDIDATE` 默认 OFF，仅此完整 AW0 候选允许开启。AW1 接纳式 anti-windup 保持开启，SB3 快速电流制动天花板继续关闭。

控制链为：

`FSM ControlIntent → 原 MotorControl_SetSpeed → SPEED S-curve → 原 speed PI + AW → 原 current PI → SVPWM / 一拍 PWM pipeline`

`FOC_EncoderSpeedUpdate` 在原有效编码器更新的约 1 kHz 路径中调用一次生成器，替换 SPEED 原线性斜坡，不串联两层 ramp。不把生成器放进 20 kHz 电流 ISR，不在 FSM 内实现控制算法。POSITION 仍使用原线性斜坡；IQ/NEUTRAL/IDLE 不经过 S-curve。

PI 参数、SB2、输出限幅、240 rpm/±0.50 A/1.6 V、300 rpm 独立超速、20000°/8 秒 rundown/12 秒会话、CONTACT/NO_ROTATION、100/40/25/3、CUR_CONFIRM、独立过流、编码器/时序保护、IRQ 优先级、A/B 逻辑全部不改。

STOP、fault、CONTACT 后的 neutral 仍走原安全输出路径，不等待轨迹减速。控制器复位及模式切换时丢弃轨迹旧目标和加速度，不能在下一次启动提交 stale trajectory。

## 初始参数与行为

参数在 `firmware_common/speed_scurve.h`，不是隐藏魔数或自动调参：

- `SPEED_SCURVE_MAX_ACCEL_RPM_S = 200.0f`，与原上/下斜坡的最大变化率相同。
- `SPEED_SCURVE_MAX_JERK_RPM_S2 = 1000.0f`，约 0.2 秒将加速度从 0 平滑建立到 200 rpm/s。
- 对称正反向和加减速；长速度变化为 jerk-up / 恒加速度 / jerk-down，短变化为三角形加速度。
- 静止到 240 rpm：0.2 + 1.0 + 0.2 ≈ **1.4 秒**，原线性为 1.2 秒。这里是参考值到达时间，不是实际电机保证达到的时间。
- 静止到 20 rpm：约 **0.283 秒**，峰值加速度约 141.4 rpm/s。
- 同模式中途改目标/反转，先以有界 jerk 释放当前加速度，再到最新目标；保持速度和加速度连续。若新目标位于当前加速度的停止距离内，参考可能暂时越过这个新目标后返回，不能通过硬裁剪假称无过冲。不会突破原/新可行目标的全局速度范围。
- 每步最多处理四段；sqrt 仅重规划时执行，常规步进为少量浮点运算。状态静态 32 B，无动态分配、HAL、UART 或 printf。无新增摩擦补偿、加速度前馈或 DOB。

没有延长 NO_ROTATION 等阈值。理想参考跟踪离线用例能在原启动期限前建立运动；实际跟踪差时仍应按原逻辑失败，不由轨迹层吞掉故障。

## 修改文件

- `firmware_common/speed_scurve.h/.c`：独立纯参考生成器。
- `foc2_app_a/Core/Src/main.c`：SPEED-only owner 和复位边界。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：默认关闭的独立 A 配置，模块单独 `-Os`。
- `firmware_common/protected_closed_loop.inc`：等长 `SPEED_CTRL=SC1` 身份，AW0/AW1/L00 旧身份不变。
- `firmware_common/control_intent_port.h`：只澄清 backend 拥有轨迹、不能重复 ramp 的注释；接口/执行逻辑未改。
- `tests/speed_scurve_host.c`、`test_speed_scurve.py`：原生算法和实际应用调用点回归。

## 构建与证据

| 构建 | Flash / 229376 B | RAM / 131008 B |
| --- | ---: | ---: |
| 新 A SC1 | 229260 B | 128832 B |
| 旧 A AW0 重建 | 228492 B | 128800 B |
| B CommonMode 重建（仅编译核验） | 228300 B | 128792 B |

SC1 比 AW0 增加 768 B Flash、32 B RAM，A 剩 **116 B Flash / 2176 B RAM**。空间非常紧，后续不能随意往 A 增加打印或诊断。

新 A BIN SHA256：`be4a89f500cd542f82e3cd1d447ee6c7ed45fabe45b55c35bcf25a62f551024f`。

新 A ELF SHA256：`608c0e98150b4de00d2a21801ed742d792fbf0d1678bd8a10510a0c8ecf89d6c`。

AW0、L00、B 旧 BIN SHA256 保持不变。重编译 B 不是刷写 B；编译产物也不是当前板上 B 镜像。

定向回归覆盖正反向长/短变化、减速、反转、升/平/降段中途改目标、频繁变化、非均匀 dt、非法 dt/目标、故障/模式复位、理想运动 admission、实际预处理 owner 的无双重 ramp 与 POSITION 保持不变。严格 `-Os/-O2` 原生测试通过；新增不兼容 CMake 组合必须拒绝构建。

完整预处理函数比较证明除 SPEED 参考与 reset 外，speed PI/AW、SB2、current FOC、PWM pipeline、CUR_CONFIRM、TWO_SAMPLE、安全 gate、FSM owner 等冻结函数不变；ADC timing 和 IRQ 对象逐字节相同。新 A 与 AW0 的编译警告集合相同，既有 unused/RWX 警告未消除，没有新增警告类型或编译错误。

最终 60 项定向回归日志：`tmp/scurve-regression-20261020-final.log`，不宣称整个历史测试仓库全部通过。

## 下一轮人工验收

尚未刷板。后续若请求实测，应使用独立 SC1 镜像及新收据，旧 AW0/L00 板测脚本的镜像/身份固定校验不得绕过。单次空载比较启动过冲、达到参考所需时间、稳态掉速、Iq、正常 STOP、50 us deadline 与 actual CCR margin；全部原保护保留。平滑参考不保证机械速度无过冲，也不替代重新板测时序。

S-curve + speed PI anti-windup 候选已就绪，等待人工空载板测。

后续已按人工确认完成 [一次 SC1 空载实测](scurve-fsm-board-20261020.md)：FOC max=31.53 µs、deadline/CCR late=0，尾段239.93 rpm，但2～7.9秒平均233.12 rpm，未证明稳速优于线性AW0。已关闭12 V并恢复原B768，不再启动。
