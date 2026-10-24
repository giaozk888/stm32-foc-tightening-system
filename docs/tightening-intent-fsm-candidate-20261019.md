# Tightening FSM / ControlIntent 解耦候选

本轮仅代码、A/B 候选编译与离线回归。**没有打开串口/ST-Link，没有刷板、复位、修改启动选择或启动电机。**
最后板端状态沿用上一轮恢复的原 B725、输出关闭、MCU 停住；本轮未重新测量板端状态，也未写入所谓正式 B。

## 边界与架构

```text
UART START/STOP（原 mailbox / 请求 ID / admission）
  → TighteningFsm_Step（100 Hz，纯 C，只决定工艺与 ControlIntent）
  → ControlIntent_Passthrough（本轮 identity trajectory）
  → ControlIntent_Apply / backend port
  → 原 MotorControl_SetSpeed / SetIq / SetIdle
  → 原 1 kHz trajectory/ramp、position/speed controller
  → 原 20 kHz Id/Iq PI → inverse Park/SVPWM
  → 原 one-cycle pending PWM / ADC IRQ entry commit

原独立保护 → 立即关闭 SD/MOE，不等待 100 Hz FSM
           → FSM 下一任务步镜像 FAULT + reason，不能再发运动意图
```

FSM 不包含 PI、前馈/补偿、observer、寄存器或 HAL/FreeRTOS API；配置/反馈/命令均显式输入，输出不携带控制器内部状态。
硬件 admission、门极关断和模式切换在单独 port/binding 中，不能靠修改 FSM 再造一条开桥路径。

`ControlIntent` 提供 mode、position/speed/Iq target、Iq/speed limit、各环 enable、reset/hold request。
本轮实际运行模式是 OFF、NEUTRAL、SPEED、IQ；POSITION 类型和扩展接口预留，但当前 port 对 POSITION/主动 integrator hold **明确拒绝并停机**，不假装已实现这些功能。
position loop 当前为 P-only，没有可重置的积分器。speed reset 只在模式入口请求，复用原 backend 的模式切换 reset；FSM 从不写积分器。
TIGHTEN 四个工艺阶段之间、TIGHTEN→HOLD 不重复 reset current/speed PI。

`iq_limit_a` 与 `speed_limit_rpm` 是约束，不是增益或任意可写阈值：当前端口只接受原 backend 已支持的对应 Iq 上限，其他上限请求拒绝；SPEED target 还必须在 speed constraint 内。
真正的超速/过流关断仍由原保护执行，不能把 intent 里的 constraint 当成高速硬件保护。

## 新旧 transition 对照

| 旧工艺状态/行为 | 新 FSM |
|---|---|
| WAIT_COMMAND（IDLE_DELAY） | IDLE |
| START 分支里混合预检、开桥、给速度 | PRECHECK（port 负责原 admission）→ RUNDOWN_START |
| RUNDOWN 中一边 arm 一边测 contact | RUNDOWN_START 建立真实运动后 → RUNDOWN |
| RUNDOWN 中累计 contact_ms | CONTACT_CONFIRM：连续严格条件＋退出迟滞 |
| CONTACT_STOP（停稳150 ms / timeout2000 ms） | CONTACT_CONFIRM 内明确的已确认/NEUTRAL settle 子阶段，保留原停稳要求 |
| SEATING_IQ → TIGHTEN_010 → 012 → 015 | TIGHTEN 中 seating/t1/t2/t3 四个工艺段；沿用原配方电流/时间 |
| HOLD → DONE | HOLD → DONE，且必须同时满足 arm/contact/tightening_completed/no_fault |
| NO_ROTATION / timeout / 底层 fault | NO_ROTATION、TIMEOUT 或统一 FAULT + 精确 reason，所有 terminal 意图 OFF |
| STOP → DONE/IDLE | 非故障状态 → IDLE、outcome=STOPPED；STOP 不清除故障锁存 |

异常表达：OVERSPEED、OVERCURRENT、CURRENT_INVALID、ENCODER_FAULT 和保护 TIMEOUT 是 **FAULT 的 reason**，不是重复的带电状态。这样任意运行保护都遵守“FAULT＋OFF”；过程启动失败和过程超时则分别使用 NO_ROTATION/TIMEOUT terminal。
原首故障框架继续保存第一原因，新的流程失败日志使用原 outcome 数字 ABI，扩展 debug 输出给出更细 reason。

### 每个状态的契约

| 状态 | 入口/正常出口 | timeout/失败 | ControlIntent |
|---|---|---|---|
| IDLE | 仅人工 START → PRECHECK | 已锁存底层保护 → FAULT | OFF |
| PRECHECK | 冻结 RAM recipe，等待原健康/零点/时序/中性PWM/admission，通过→RUNDOWN_START | 1000 ms/无效配置/拒绝admission→TIMEOUT/FAULT | OFF；尚未开桥 |
| RUNDOWN_START | 运动持续建立→RUNDOWN | 持续高驱动但未建立运动→NO_ROTATION；原 rundown timeout/travel 仍有效 | SPEED |
| RUNDOWN | 已 arm，满足严格掉速+负载条件→CONTACT_CONFIRM | rundown timeout/travel→TIMEOUT | SPEED |
| CONTACT_CONFIRM（pending） | 连续满足 contact_ms→确认接触并转 NEUTRAL settle | 条件明显解除→RUNDOWN；灰区清确认计时；rundown timeout仍有效 | SPEED |
| CONTACT_CONFIRM（confirmed） | 保留原≤2 rpm持续150 ms停稳→TIGHTEN | 超过2000 ms→TIMEOUT | NEUTRAL，零电流命令，不消耗原 session 后再重开桥 |
| TIGHTEN | 四段原配方依次完成→HOLD | 原 torque_abort_rpm / post_travel_max_deg / session timeout / 任何保护→失败OFF | IQ |
| HOLD | hold_ms完成且成功条件齐全→DONE | 与TIGHTEN相同；缺任何成功前置条件→FAULT | IQ |
| DONE | OK保持；可接受新流程命令，但原单次boot/session admission约束不变 | 新底层故障仍FAULT，不能自动重启 | OFF |
| NO_ROTATION/TIMEOUT/FAULT | 保存首失败原因；需人工恢复/复位 | STOP不能清除故障 | OFF |

全流程仍受原 12 s 单次 session lease；100 Hz 观测间隔大于30 ms视为过程TIMEOUT，不能把缺失观察间隔计入 contact 连续时间。

## 起转与 CONTACT

起转复用已通过的 `TightenRundownGuard`，不把 travel-only/单个速度尖峰当成起转：

- 正方向 **ctrl 和 detect** 都达到 `max(10rpm, 0.5*command)`；
- 连续100ms，同时同一窗口正向机械净位移≥3°；
- 20rpm试验下条件不满足且 elapsed≥1500ms、signed IqRef≥0.30A持续250ms → NO_ROTATION；低需求则仍由原 rundown timeout 收口。

只有 arm 后可检测 contact。严格速度门槛为：

`min(recipe.contact_rpm, 已建立运动期间双速度共同峰值 * 0.70)`。

因此即使只稳定在10rpm并完成motion arm，也不能因为“10rpm低速＋高Iq”马上被认为掉速接触。必须确实下降。
严格负载条件沿用 `signed IqRef >= recipe.contact_iq_mA/1000`，连续时间沿用 `recipe.contact_ms`（默认250ms）。
退出迟滞明确为 speed +2rpm / load -0.03A；灰区允许保持 CONTACT_CONFIRM 状态，但**清除连续严格确认计时**，不靠迟滞吞掉不满足条件的时间。
这些是新的流程接触策略，不是降低过流/超速/采样保护阈值。

`fsm_enter_state` 集中维护 previous/current state、计时、travel起点、arm/contact标志、reset请求和outcome。
contact-settle与TIGHTEN工艺段入口也分别集中为 `fsm_enter_contact_settle` / `fsm_enter_tighten_phase`，不在多个控制分支重复操作PI。

## 安全接入的一个必要区别

原 `ProtectedLoop_Ready` 包含 `!Tightening_IsBusy()`。新 PRECHECK 对 UART/SET/另一个 START 必须保持 BUSY，否则配方会被并发修改。
所以只对该候选增加一个窄例外：**FSM=PRECHECK，intent=OFF，三个环enable均0** 时允许执行原 admission 检查。
其余原 health、零点、encoder freshness、neutral PWM、timer、fault、UART、FW-update、mode-IDLE 检查全部保留。
离线回归将该例外从预处理函数中移除后，验证其余 readiness 表达式与原版逐字一致；`LatestOriginal_Admit` 函数本身保持不变。
没有为 RUNNING、TIGHTEN、FAULT 放行，也没有新增恢复门极输出的路径。
候选另外将原 `MotorJob_QueueStop` 的“立即关桥＋发布STOP mailbox”放在任务级critical section内，防止任务切换把人工STOP误判成session意外丢失；原STOP关断函数/顺序仍保留。
这是BASEPRI任务调度边界（FreeRTOS syscall priority=5），不更改NVIC优先级，也不屏蔽高于该边界的ADC/硬件安全IRQ。正常非候选构建的STOP路径不变；真实函数的主机回归检查退出critical前门极已关且mailbox完整发布。

## 保持不变与实验上限的范围

候选从原 `RundownGuardTrial` 的受保护 SB3 backend 派生，而不是从最近的固定 Iq 实验 profile 派生。
speed PI Iq上限仍0.40A，direct-Iq上限仍0.20A；配方的seating/t1/t2/t3/hold电流、时间和停止参数不变，没有自动增流。
正式backend原超速门槛60rpm不改。此前150rpm仅属于单独固定0.45A诊断，不推广至本候选或正式B，也没有改写那个诊断preset的150设定。

预处理函数逐项比较 current loop、outer/position/speed loop、reset、PI、Park/Clarke、SVPWM、CUR_CONFIRM、current validator、guard、encoder angle、PWM pipeline；与原 backend一致。
ADC timing / IRQ对象与原backend逐字节一致。electrical zero=10507、direction=-1、pole pairs=10、采样/IRQ优先级都未改。

## UART 与算法预留

START/STOP仍走原 `MotorJob_HandleUartStart` / `MotorJob_QueueStop` mailbox和请求ID；STOP原来的立即硬关断调用保留。
原 STATUS ACK（STAGE/BUSY/MODE/OUTCOME/CONTACT等）保持，STAGE使用旧数值兼容映射。
另发两行 `0 EVT FSM REQ=...`，包含：

- FSM_STATE / PREV_STATE / STATE_TIME_MS
- RUNDOWN_ARMED / CONTACT_PENDING / CONTACT_CONFIRMED
- MOTION_TRAVEL_DEG（值附mdeg）/ SPEED_TARGET（mrpm）/ IQ_LIMIT（mA）
- CONTROL_MODE / OUTCOME / FAULT_REASON

CONTROL_MODE: 0=OFF、1=NEUTRAL、2=POSITION（当前拒绝）、3=SPEED、4=IQ。
状态字段为本次流程**意图**，不是GPIO/PWM实测证明。原 `MOTOR TEST STATUS` 的SD/MOE/CCER仍用于确认输出状态。
候选 RESULT 的ACK/结束帧保留，摘要文案压缩为START_REQ/RESULT/CONTACT/角度整数毫度，五段原统计继续打印；CONTACT=0时角度字段不可当成真实接触证据。
只压缩候选文案及使用冷流程代码 `-Oz` 来满足 A 槽容量，未压缩/改动实时控制数学。

`ControlAlgorithmExtensions` 仅定义 trajectory_generator、friction_feedforward、acceleration_feedforward、speed_anti_windup、dq_decoupling、DOB 的输入/输出契约，未注册或调用任何实现。
本轮identity trajectory后仍走原 ramp；以后补算法应接在reference/controller边界、受同一保护和约束，不能把算法塞回FSM。

## 修改文件

新增：

- `firmware_common/control_intent.h`：意图/轨迹/反馈/扩展接口。
- `firmware_common/control_intent_port.h`：失败关闭的backend适配契约。
- `firmware_common/tightening_intent_fsm.h`、`.c`：纯流程核。
- `firmware_common/tightening_intent_binding.inc`：原UART/recipe/session/control API接入。
- `tests/tightening_intent_fsm_host.c`、`tests/test_tightening_intent_fsm.py`。
- 本说明。

接入变更：A/B各自的 `Core/Src/main.c`、`CMakeLists.txt`、`CMakePresets.json`；`firmware_common/protected_closed_loop.inc` 的PRECHECK窄例外；`firmware_common/motor_job_port.inc` 的候选STOP任务原子发布；README入口。
工作区此前已有的 torque/angle 诊断、脚本和第三方目录改动不属于本轮重写，不回滚或混称为本轮成果。

## 离线验证与构建

使用 `TighteningIntentCandidate` configure/build preset，两槽独立构建目录；宏 `FOC_INTENT_FSM_CANDIDATE` 正式默认OFF，原task在非候选构建保持原实现。

| 候选 | Flash / 229376B | RAM / 131008B |
|---|---:|---:|
| A | 229220B（余156B） | 128192B（余2816B） |
| B交叉构建 | 228212B（余1164B） | 128176B（余2832B） |

Flash余量很紧，不能直接叠加新补偿算法；未来必须再次审计尺寸。`.su`显示task自身局部栈约520B、STATUS自身约560B、新debug formatter自身约344B，**不是完整调用链最大栈，也不是实机high-water**。
构建保留原unused和RWX链接警告，未将警告当作保护验收。

新增7项Python定向回归通过。其中真实C核心与backend契约分别按 `-Os/-O2` 编译运行，覆盖正常流程、NO_ROTATION、单点毛刺不arm、未arm不CONTACT、持续/瞬时/迟滞contact、正反向、各运行状态×各保护原因、STOP优先、故障不被STOP清除、超时、travel、NaN/无效编码器、tick wrap、坏intent拒绝以及不满足完整成功链绝不能OK。
另核对默认OFF、候选编译接入、原控制数学/IRQ对象不变、PRECHECK例外与UART字段兼容。

不能把定向通过描述为全仓全绿；已有历史基线/原始备份依赖及Python/C模拟预期问题需要单独列出。

最终候选SHA-256：

- A BIN：`f010e5a63ce2e0cc7362b91809ac4bb5c2c53708c4be22ab6efe472e2169cda9`
- A ELF：`6594f451d10943761b2542dbd207e6ea0abeb00cf218a3c56a840f19e72b2b10`
- B候选BIN：`7192de7942112e7cdf7dae8bf1a09ed1a3df37c1449b81221020fc4b40d63069`

本轮首遍全仓discover：1374项、18 failure /4 error，日志 `tmp/intent-fsm-all-regression.log`；失败/错误用例名称集合与此前 `tmp/angle-chain-all-offline-20261019.log` 完全一致，不等于证明每个历史失败的内部原因完全相同。
包括旧源码字面/哈希基线断言、历史镜像尺寸/身份、未公开的原始备份权限、native/Python仿真差异，以及旧工具取第一个动态诊断宏分支误当成默认0.4A等问题。未以修改控制参数让这些遗留测试变绿。
收尾又运行一遍全仓：**1375项、18 failure /4 error**，355.355秒；日志 `tmp/intent-fsm-all-regression-final.log`。失败/错误用例名称集合与前一份历史记录仍一致，没有新增失败用例名称，但全仓并未通过。
全仓第二遍启动时该模块收集6项；STOP原子发布回归在收尾新增，最终源码的候选定向7项已另行复跑全过，日志 `tmp/intent-fsm-tests-final.log`；不能将此描述为最终源码的原子全量全绿。
最终构建日志 `tmp/intent-fsm-build-a-final.log` / `...-b-final.log`。每槽保留原12条unused及1条RWX链接warning，新增纯C核心在host `-Wall -Wextra -Werror` 下通过。

## 第一轮人工空载验收（未执行）

1. 电机空载固定、可立即断电；12 V关闭，MCU稳定。核对IU→PA0、IV→PA1、PC6→CTRL_SD及原U/V/W，不换相、不重设零点。
2. 核对实际当前槽位；只在确认B回退可用后写非活动A，完整回读并比对bootloader/B/配置区未变。**不能直接复用旧诊断脚本的BIN/ELF hash或baseline。**
3. 人工开启12 V、限流0.5 A、无报警后，通过正常A/B健康确认与复位；此时不发START。验证零点4000 valid、READY、无fault、SD/MOE/CCER=0。
4. 等待本次启动的真实Monitor timing：FOC<50us、deadline miss=0、actual CCR late=0、margin有明确余量；同时查栈high-water、UART是否截断/丢行。未通过就停止，不改阈值重试。
5. 读GET参数，只有人工确认后才在RAM设RUNDOWN_RPM=20并GET回读；不SAVE、不改变原各段电流/时间/保护。若原recipe不符合受保护backend的20rpm及12s窗口，START必须拒绝，不能偷偷改配方。
6. 一次UART START；观察PRECHECK→RUNDOWN_START→RUNDOWN，真实速度/位移建立后才能ARMED=1。首轮建议观察约2秒后人工STOP；这不是新写入固件的2秒限制，原12秒session保护仍在。
7. 空载预期保持RUNDOWN而非CONTACT/DONE/OK；不起转应明确NO_ROTATION。若空载出现CONTACT，作为待查证据停止，不声称真实接触。空载不能验收负载TIGHTEN/扭矩精度，正常全链先由离线受控反馈验证。
8. 任一fault、方向/电流异常、时序不满足立即停机，保护不能等100Hz状态机；STOP后核验SD/MOE/CCER=0。保存匹配BIN/ELF/Flash/RAM及调试字段；12V关闭后只恢复原B启动选择，不自动重试或升流。

状态：FSM重构候选只完成离线准备。未用编译/仿真代替电机空载、工件接触或扭矩精度验收。

FSM 重构候选已就绪，等待人工空载板测。
