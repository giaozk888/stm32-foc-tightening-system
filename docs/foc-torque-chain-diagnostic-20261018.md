# FOC 扭矩链核对与手动低电流诊断准备

本文保留历史50mA方案及其证据；最新固定±0.10A准备见 [100mA诊断说明](torque-chain-100ma-diagnostic-20261018.md)。两个预设的幅值不可混用。

范围：仅源码核对、诊断构建和离线测试。本轮不连接调试器/串口、不刷板、不改变启动选择、不发送运动命令。不能据此宣称物理相序、电角零点或真实转矩已通过。

## 结论先行

`Iq ≈ IqRef` 只证明在**当前采样映射和软件角度坐标系**中跟踪；不等于实际磁链 q 轴电流正确。若软件角度相对磁链差 δ，即使软件 Id=0，实际转矩电流仍可能约为 `Iq_sw*cos(δ)`。因此不能用低 Id、软件自洽或未饱和单独证明正确转矩。

没有找到足以支持直接换相、翻转电流符号、修改 PI 或电角零点的证据。本轮未做这些修改。之前 2.77 rpm 是历史观测，本轮没有重测，也没有把新的诊断准备说成已解决实际不起转。

## 当前软件映射

| 环节 | 源码约定 | 物理证明边界 |
| --- | --- | --- |
| U 功率命令 | SVPWM `du` → plan.phase[0] → pending.ccr[0] → TIM1 CCR1 → PC0/CH1、PB13/CH1N | 预期 UH/UL；驱动板 U 与电机绕组对应需实机确认 |
| V 功率命令 | `dv` → phase[1] → pending[1] → CCR2 → PC1/CH2、PB0/CH2N | 预期 VH/VL；实物需确认 |
| W 功率命令 | `dw` → phase[2] → pending[2] → CCR3 → PC2/CH3、PB1/CH3N | 预期 WH/WL；实物需确认 |
| 电流 U | PA0 → ADC1 IN1 injected rank1 → hadc1.Instance->JDR1 → u/raw_u | 预期接 IU；不能靠软件变量名证明接线 |
| 电流 V | PA1 → ADC2 IN2 injected rank1 → hadc2.Instance->JDR1 → v/raw_v | 预期接 IV；不能靠软件变量名证明接线 |
| 电流转换 | 默认 sign=-1，`Iu=(zero_u-raw_u)*scale`、Iv 同理；scale=3300/(4095×120) A/count；Iw=−(Iu+Iv) | 传感器增益、正电流方向与物理绕组仍需确认 |
| Clarke | α=Iu，β=(Iu+2Iv)/√3 | 要求与以上 U/V/W 正序一致 |
| Park | Id=αcosθ+βsinθ；Iq=−αsinθ+βcosθ | θ 必须确实对齐磁链 d 轴 |
| 编码器机械方向 | ENCODER_DIRECTION=-1；raw 减小 → signed mechanical angle/speed 增大 | 不能指定看轴端的顺/逆时针，现场视角和安装方向需确认 |
| 电角度 | θe=wrap(−10×Delta14(raw,10507)×2π/16384) | 10 极对，零点10507；硬件匹配未被证明 |
| 预测/控制角 | 1kHz 接受样本与时间戳生成 θe、ωe，并沿用现有 sample-age 和20kHz预测；Park使用 cl_frame.measurement_angle | 保留现有算法及数据年龄保护，未加入 observer |
| inverse Park | Vα=Vd cosθ−Vq sinθ；Vβ=Vd sinθ+Vq cosθ | 与 Park 代数互逆，不等于物理角度正确 |
| 相电压 | Vu=Vα；Vv=−Vα/2+√3Vβ/2；Vw=−Vα/2−√3Vβ/2；共同 min/max offset | 映射最终仍取决于三路物理接线 |
| PWM | PWM1、主/互补极性 HIGH；CCR preload；原一拍 pipeline ADC入口提交 | CCR读数不是示波器/电流实测；PA11 CH4是ADC时序，不是W相 |

正 Iq 的理论方向：**在相序、相电流正方向、磁链 d 轴对齐都成立的前提下**，应使 signed mechanical angle 增大，即 AS5047P raw 减小；负 Iq 相反。当前不能宣称这个前提已经实物成立。

源码路径（A/B相同）：

- `Core/Src/stm32g4xx_hal_msp.c`：ADC及TIM1引脚。
- `Core/Src/main.c`：ADC初始化、Encoder_ElectricalAngleRad、FOC_EncoderSpeedUpdate、FOC_CurrentLoopStep、PWM_SetDuty。
- `firmware_common/protected_adc_irq.inc`：同步 injected pair 读取，ADC1独立中断所有权。
- `foc_feedback_safety_candidate.h` / `foc_current_feedback_polarity.h`：原码安全链和电流转换。
- `foc_pwm_pipeline_binding.inc` / `foc_adc_timing_stm32.c`：phase→pending→CCR真实提交。

## 电角零点来源和变更核对

`ELECTRICAL_ZERO_RAW=10507U` 是编译期常量，来自 A/B main.c；不是 KVS 当前校准结果。Git 初始导入681ab39与当前5eeae2e均为10507、方向−1、极对数10。本轮未找到与当前物理相序绑定、证明 d 轴对准转子磁链的电角校准流程/记录。SPI parity、启动角度有效和电流零点成功都不能替代电角校准。

历史代码确实包含 PWM pipeline、角预测/时间戳、编码器IRQ、原码零点admission等改动，最近聚合提交5eeae2e包含这些内容；不能把它当成独立物理对齐证据。当前 U/V 电流换线历史尤其需要实物核对。本轮不追溯猜测一个新的经验 offset。

## 仅诊断构建

新预设 `TorqueChainDiagnostic` 继承完整 SB3 + RundownDiagnosticTrial；`FOC_TORQUE_CHAIN_DIAG` CMake默认OFF。A/B普通构建完全没有该入口。不是正式控制模式，也未获带电验收。

```powershell
# 在 foc2_app_a 或 foc2_app_b 目录内，仅构建；以下不会刷写。
cmake --preset TorqueChainDiagnostic
cmake --build --preset TorqueChainDiagnostic --parallel 6
```

- Iq固定 ±0.050 A，IdRef固定0；不允许任意电流输入，不扩大现有限流。
- 使用原 MotorControl_SetIq / MOTOR_MODE_IQ，绕过速度PI；正常电流PI、坐标变换、SVPWM和全部既有故障链仍执行。
- 复用唯一 LatestOriginal_Admit 功率事务，保留校准、启动确认、neutral commits、timer/encoder/current/timing预检。只替换诊断入口的配方检查，不重写/保存配方。
- 新命令只允许本地UART控制台，沿用外围 LOCAL_CONSOLE_ONLY 限制。普通 START、RPC START 不允许启动本诊断。
- 每个boot最多一次请求；任何失败不自动重试，不自动接着反向，不自动扫角。偏移在输出关闭时选择，并至少等待下一次接受的完整 encoder/outer update 才允许准入。
- 该诊断的单次 lease 缩短为200000us，由原 ADC commit permit 和独立TIM7截止检查停止。没有更改普通配方、保护阈值或原12s状态机lease。任务STOP/冲突START取消诊断并走原ProtectedLoop_Stop。
- 不能绕过真实电机接线、供电、固定和可断电的人工检查；这里只准备代码。

人工上板另行授权后，可选择一个命令（均需按现有协议加请求ID；**本轮未发送**）：

```text
MOTOR TEST TORQUE STATUS
MOTOR TEST TORQUE POS ZERO CONFIRM
MOTOR TEST TORQUE NEG ZERO CONFIRM
```

小范围角偏移仅准备 `POS/NEG PLUS5 CONFIRM`、`POS/NEG MINUS5 CONFIRM`。这里的±5是**电角度**，不是机械角度。每个选择也只发一次±50mA/200ms脉冲；需要另一次人工测试/正常重新预检才能更换选择。拒绝90°、任意数值和无CONFIRM命令；不会自动选择、写Flash或保存新的电角零点。

## 连续诊断窗口与解释

复用32×124B现有 `cl_startup`，不增加另一大缓冲。约8ms一帧（125Hz抽取），200ms通常约25帧，再保留终止/首次故障帧。捕获发生在已接受encoder的1kHz任务；ISR不增加printf、UART或格式化。

包含 IqRef/Iq/Id、Vq/Vd、IU/IV原码、encoder raw/delta/dt/timestamp、机械/电角度及预测角、speed instant/filtered、validator/current_path、PWM pending与CCR preload读回、门状态等。注意：这是连续抽取的任务快照，不是20kHz逐点同步测量，不能排除8ms以内抖动；Iq/Id在拒绝帧可保留上一有效FOC结果。诊断的speed_cmd字段为0而非闲置拧紧配方转速。

轻量实际CCR提交统计使用 `foc_pwm_write_profile.points`；此前Rundown记录的 `.writes` 在轻量配置中不增长。本轮只修新torque构建记录，未改变既有Rundown镜像、实际提交或其时序判据。

新 `tools/torque_chain_decode.py` 只读已保存文件：

```powershell
python tools/torque_chain_decode.py --elf foc2_app_a/build/TorqueChainDiagnostic/foc2.elf --sram <已保存SRAM.bin>
# 或已抽取trace，明确提供人工测试的符号和偏移：
python tools/torque_chain_decode.py --trace-bin <cl_startup.bin> --sign 1 --offset-deg 0 --iq-ma 50
```

可执行上述文件解码不意味着捕获身份已独立认证；仍需匹配ELF/Flash和板测收据。

输出 mean_abs_Id、mean_abs_Iq、mean_Id、mean_Iq、abs比值、Iq误差、平均速度、机械净行程、Vdq、正/反向运动区间及静止区间。一个encoder LSB只用于离线分辨率判读，不是新保护阈值。不会自动调整零点、PI或电流限值。

判读分支：

1. Iq跟踪好、Id低、±Iq方向正确且有持续角位移，才进一步考虑静摩擦/齿槽/机械负载；50mA不动本身不足以判定这些。
2. Iq跟不上或反向、Id明显、Vdq接近限幅：优先核对电流物理映射/符号、磁链角与采样，不自动换相。
3. encoder delta/dt正常而速度估计跳变：核对估计器/时间戳。
4. raw角度/解包异常：核对SPI/DMA/unwrap/方向。

即使全部软件项良好，也不能从软件Iq直接验收N·m。需要后续人工比较空载/脱开负载、逐小步电流响应或起动摩擦电流；不在本轮自动提高Iq。

## 构建和回归

六个相关构建全部链接成功（Flash/RAM均为链接器Used Size；不是剩余动态堆/栈余量）：

| 预设 | A Flash / RAM (B) | B Flash / RAM (B) |
| --- | --- | --- |
| RundownGuardTrial | 228924 / 127992 | 227916 / 127976 |
| RundownDiagnosticTrial | 228220 / 130080 | 227204 / 130064 |
| TorqueChainDiagnostic | 229132 / 130096 | 228108 / 130080 |

A诊断仅余244B Flash、912B链接RAM，不能随意叠加其他trace。未改变分区或删保护来适配空间。

最终Torque A BIN SHA256：`f9c87c42f7ee52dd058901ac29fc3eac62556a5d5db109cd7bb825bd8c74a808`；ELF：`3bc0a75f88e5136bb8811908c01ed3222be4191c2494e2e2f1d4aeaba1f7763f`。

Torque B BIN：`c522a73023c1a5046a1c072bec5ea65d103e6da26746f36c87271ba55ba259e9`；ELF：`df8df7a2d64a68c2788a040c56e9074585130e392490b736be5e261ad7167be9`。

原Rundown A BIN/ELF仍为`a9c5cf73.../ba82c420...`，与先前板测收据完全一致。预处理后FOC、encoder处理、TWO_SAMPLE、原码保护、CUR_CONFIRM、TIM7、PWM pending等冻结函数一致；ADC timing与IRQ编译对象哈希相同，未改20kHz算法。电角helper只有诊断构建才添加人工选定offset，默认0。

`test_torque_chain.py`最终5组通过，包含实际C编译运行的生产准入/命令/任务owner（-Os和-O2）、初始化/首次手动/正反命令/IdRef0/单boot一次/200ms lease/STOP/故障/准入计划期间插入STOP或fault/角度wrap/8ms轨迹冻结、映射与默认OFF检查、IQ分支不进入速度PI、控制/保护预处理及对象一致性、统计/元数据ABI解码。`test_rundown_isolation.py`另行3组通过，现有状态机与正常内核不变。

全量 `python -m unittest discover -s tests`：1227项，1214通过，9失败、4错误，耗时377.683s。失败/错误方法集合与本轮前`tmp/rundown-final-all-tests.log`的13项逐名比较完全相同；没有为了全绿修改历史断言。日志`tmp/torque-chain-all-tests.log`。全量后补充元数据和准入race用例并重跑上述5组全部通过。因此**不能报告全部离线测试通过**；历史不通过项仍待独立处理。

两个槽新构建告警集合与既有RundownDiagnosticTrial一致，没有新增warning/error；原有未使用函数/变量、RWX段和第三方告警未在本轮消除。`git diff --check`通过。

没有硬件操作，没有上板耗时或±Iq机械响应新结果。原B启动选择未触碰。
