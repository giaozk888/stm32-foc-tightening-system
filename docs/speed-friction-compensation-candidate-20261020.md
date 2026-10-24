# FR1：A-only 库仑摩擦补偿候选（2026-10-20）

本轮仅代码审查、离线测试和编译。未访问板端、未刷写、未复位、未修改B或启动选择、未启动电机。保留上轮AF1的BIN/ELF以解码已有板测记录，不能用新的FR1 ELF解码旧AF1记录。

## 用户修订后的初值

最初拟用0.020 A（原0.50 A上限的4%）；本轮用户随后明确要求直接取 **0.20 A**，因此最终初值为0.20 A、deadband为2 rpm。0.20 A是现有Iq限幅的 **40%**，不是原要求3%～5%的小幅补偿，也不是已标定出的摩擦电流。可能明显占用PI/加速度FF余量、增加起步跳变，不能因为离线限幅通过就宣称实机合适。

可配置CMake cache：`FOC_FRICTION_I_A=0.20`、`FOC_FRICTION_DEADBAND_RPM=2.0`；对应 `SPEED_FRICTION_I_A`、`SPEED_FRICTION_DEADBAND_RPM`。配置拒绝负数/非有限数，首版拒绝大于原0.50 A上限的补偿参数，不改变原Iq/过流保护阈值。

## 公式和接入

```
iq_fric = FRIC_ON && abs(speed_ref) > deadband
        ? I_FRIC * sign(speed_ref) : 0
iq_acc_ff = FF_ON ? Ka * existing_scurve.accel_ref : 0
iq_pi = existing_p_term + admitted_speed_integrator
iq_raw = (iq_pi + iq_acc_ff) + iq_fric
iq_ref = clamp(iq_raw, -existing_iq_limit, existing_iq_limit)
```

只在MotorControlTask原约1kHz SPEED分支、S-curve之后应用。FRIC使用**参考速度**而不是测量速度的符号；恰好±2 rpm及区间内为0。首次越过deadband时±0.20 A是本模型有意产生的阶跃，没有擅自加入平滑、滞环、Stribeck、LuGre、DOB或速度前馈。

FRIC OFF、I_FRIC=0或deadband内，直接调用原 `SpeedAccelFf_Apply`，保持原AF1控制数值。补偿有效时，原条件积分/边界接纳语义扩展到三项合成的tentative raw/ref：向饱和方向增加积分时，仅接纳到 `±iq_limit - iq_fric - iq_acc_ff - p_term`，退积分和既有强制卸载保持原行为，最后统一clamp。没有先把PI单独钳位后再绕过限幅追加补偿。

POSITION/IQ/NEUTRAL/IDLE分支不加入摩擦项。current PI、speed PI Kp/Ki、积分硬限幅、既有SB2/已关闭SB3选择、S-curve/Ka、Clarke/Park/SVPWM、电角度/相序、CURRENT_INVALID/TWO_SAMPLE/CUR_CONFIRM、one-cycle PWM提交、IRQ/时序/过流/编码器保护和FSM均保持不变。

## 构建与运行开关

A新preset：

- `Tightening240rpmFrictionOnCandidate`
- `Tightening240rpmFrictionOffCandidate`

都继承AF1 FF ON（Ka=0.0001875、最大FF37.5mA）及压缩日志。`FOC_SPEED_FRICTION_CANDIDATE` 全局默认OFF，B没有此开关/模块。新身份 `SPEED_CTRL=FR1`，旧AF1及更早候选身份不改。

原UART机器协议保持，候选新增RAM-only接口：

```
MOTOR TEST FRIC ON
MOTOR TEST FRIC OFF
MOTOR TEST FRIC STATUS
MOTOR TEST FRIC METRICS POS
MOTOR TEST FRIC METRICS2 POS
MOTOR TEST FRIC METRICS NEG
MOTOR TEST FRIC METRICS2 NEG
```

ON/OFF只能在FSM空闲、无排队START/STOP、MODE_IDLE且SD/MOE/AOE/CCER关闭时切换。检查与开关更新在任务临界区完成；格式化在临界区外。不会改PI状态、清故障、重新装填lease、保存KVS或发送运动命令。切换FRIC/FF和控制器/新SPEED模式复位时仅清诊断统计；退出SPEED保留结果。先保存指标，再切换或复位，防止擦掉证据。

## 压缩日志

保持原32 B token缓冲/传输链，MonitorTask约10Hz发三条记录，用同一seq关联：

- FRC R：speed_ref、speed_meas、accel_ref、command、FF/FRIC开关、ms。
- FRC C：iq_pi、iq_acc_ff、iq_fric、iq_raw、iq_ref、saturation flag。
- FRC I：speed_integrator、外环采样的iq_meas。

FR1用以上三条替代原两条AFF日志，不重复发送；AF1旧构建仍发原AFF。真正编码器/最坏uint32计数/负浮点回放和匹配ARM ELF验证消息<=32B，格式字典不进入BIN。ISR不printf、不UART、不写日志；在线统计在IqRef发布后生成。新增统计和第三条低频日志仍有开销，板测需重新核验deadline、CCR margin、任务栈和队列丢弃，不能以算法冻结推断时序一定不变。

## A/B指标定义

POS/NEG按command方向分开，约1kHz有效更新按实际dt加权：

- 起转延迟：最新非零command段开始，参考已超deadband、同向实测速度>=2 rpm持续50ms时，回填该连续窗口起点；不成立返回-1。这是**测量判据**，不改变rundown_armed/NO_ROTATION。短暂速度毛刺不能建立起转。零目标后相同命令重新启动会重置该延迟，不沿用上次值。
- 低速MAE：deadband < abs(speed_ref) <=30 rpm时的abs(ref-meas)加权平均。
- 匀速MAE：参考抵达command（差<=0.001 rpm）且abs(accel_ref)<=0.001 rpm/s时的误差；没有符合窗口返回-1。
- speed integrator峰值、合并前Iq_PI峰值、限幅后IqRef峰值、外环采样Iq反馈峰值，均取绝对值。
- signed mean speed、wrong-direction time；后一项仅在参考已指向目标方向时统计，反转轨迹仍正常制动阶段不误算为异常方向。
- 目标为0的停止段不归入POS/NEG；同方向多段峰值/误差累计，起转延迟表示该方向最新command段，比较时应从静止、相同命令/窗口开始。

`tools/friction_compare.py off.log on.log`只读保存的STATUS与每方向METRICS/METRICS2，输出ON/OFF差值及正负速度幅值/起转延迟不对称。只允许FRIC开关不同，I_FRIC、deadband、FF开关和Ka必须一致；混合快照拒绝，缺方向/缺阶段显示null，不填假零。mean speed的负号保留，不误当成未测。没有共同实测方向则拒绝比较。

软件支持正负参考并有离线对称测试；当前原FSM的TIGHTEN_DIRECTION仍为原固定方向，未新增自动反转运动入口，未更改相序/编码器方向。不能以一次正向FSM测试代替正反转一致性板测；负向需后续人工许可的现有signed-SPEED入口或单独准备的方向诊断，本轮不扩大运动权限。

## 修改文件

- `firmware_common/speed_friction_compensation.h/.c`：纯C库仑补偿、统一AW及方向指标。
- `firmware_common/speed_friction_compensation_binding.inc`、`speed_friction_compensation_log.cc`：安全RAM开关和压缩日志。
- A `Core/Src/main.c`、`CMakeLists.txt`、`CMakePresets.json`：SPEED-only接入/配置。
- `firmware_common/speed_accel_feedforward_binding.inc`：仅FR1条件编译的诊断复位/日志路由；原AF1数值和日志路径不变。
- `firmware_common/protected_closed_loop.inc`：FR1命令/身份，B条件编译后不变。
- `tools/friction_compare.py`。
- `tests/speed_friction_compensation_host.c`、`speed_friction_log_host.cc`、`test_speed_friction_compensation.py`。
- README和本文。

## 最终构建与离线验证

| 构建 | Flash / 229376 B | RAM / 131008 B |
| --- | ---: | ---: |
| A FR1 FRIC ON | 217420 B | 129152 B |
| A FR1 FRIC OFF | 217420 B | 129160 B |
| B原CommonMode，独立目录重编译 | 228300 B | 128792 B |

ON/OFF分别剩1856/1848 B静态链接RAM，不等同于任务可用栈。新A较AF1增加2520 B Flash；功能默认关闭，B不加入模块。

- ON BIN SHA256：`c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8`。
- ON ELF SHA256：`91a1d63509efefedb2bd89cb0281a65995aac9eaaed64c7964ae2d06c28e306d`。
- OFF BIN SHA256：`8c4b0c23359e3b85b509d8d67ba95f06679c0ee1bd2230a73b9201c9ca6ffd20`。
- B BIN SHA256：`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，与原B构建逐字节相同，不是刷写板上稳定B。

新增8项定向测试（`tmp/friction-new-regression-final.log`）、既有61项回归（`tmp/friction-existing-regression.log`）及12项共享UART/日志等CTest（`tmp/friction-ctest.log`）通过。覆盖正反/精确deadband和相邻float、长时饱和无windup、退积分、FRIC OFF与原AF1数值一致、实际速度owner、POSITION未变、模式/复位/命令安全门、方向指标及缺失数据、3条真实32 B token和ARM ELF。

预处理冻结函数比较通过，ADC timing/IRQ/S-curve/原加速度FF对象逐字节相同，保留旧AF1 BIN和ELF校验值。新主程序无新增警告类型，新纯C/C++模块在严格native警告检查下通过；链接器仍有原RWX及主程序unused警告。首次并行编译因主机内存不足失败，改为串行后最终三种构建均成功，不隐瞒初次环境失败。

本轮没有板测：FOC实时耗时、任务栈、日志队列和0.20A的物理效果均待新收据验证。板端保持上轮人工关闭12V、原B772已确认/停在入口的状态；本轮未访问设备，也不把旧板测数值套给FR1。

## 人工板测A/B步骤（未执行）

1. 后续人工授权并确认电源/空载固定后，只更新非活动A、完整回读并保留B。使用新FR1镜像/ELF和新收据，不绕过旧AF1/SC1脚本的固定hash/身份检查。
2. 保持原12V/0.5A电源、±0.50A Iq限幅和全部保护，先校准/时序/栈预检。确认Ka、FF ON、I_FRIC=200000uA和deadband=2000mrpm。0.20 A不是小补偿，先限定空载观察，不能把其当成已有摩擦标定值。
3. 同一镜像在输出关闭空闲时FRIC OFF，独立运行一次原配方；停机后、复位前保存FRC STATUS及POS/NEG两组METRICS、METRICS2和完整日志。
4. 独立准备另一轮，完全相同目标/方向/初始静止/负载/电源/覆盖窗口，仅FRIC ON，采相同指标。开关不重装一次性lease，故障或预检失败停止，不自动重试。
5. 匹配ELF解码，比较启动延迟、低速/匀速MAE、积分器/Iq_PI/总Iq峰值；负方向需独立获准的同幅值测试，不能自动串联或把缺失方向当通过。用比较工具核对正负一致性。任何Iq反馈峰值仍是软件估计，不是独立电流/转矩标定。

摩擦补偿候选已就绪，等待人工板测

随后人工确认完成[一次正向FRIC OFF/ON空载对照](friction-off-on-board-20261020.md)：ON起转更快、匀速MAE和积分器峰值降低，但低速MAE、Iq指令峰值和过冲增大；两轮deadline/CCR late=0，不能宣称全面改善或正反一致性通过。已关闭12V、恢复原B启动选择（generation780）并停在入口，不再运行。
