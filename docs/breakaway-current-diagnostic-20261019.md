# Breakaway-current诊断：逐档、双向、手动单次

后续用户已改为自动逐档、每档 5 秒；新版说明见 [5 秒批测](breakaway-five-second-batch-20261019.md)。本页保留原 200 ms 版本及历史构建证据，不代表新的执行安排。

本轮完成源码、A/B编译、离线测试和已有记录回放，**没有刷板、复位、开启功率桥或启动电机**。用户要求中既有“不刷板、不自动启动”，又要求离开现场后直接完成实验；本轮停在离线准备，不进行无人现场电机实验。没有新增硬件实测，不伪造breakaway或摩擦补偿数值。当前板端供电/运行状态没有重新核验，也不依据上一轮断电记录宣称此刻电源关闭。

## 构建开关与控制边界

- 默认关闭：`FOC_BREAKAWAY_CURRENT_TEST`。A/B专用预设：`BreakawayCurrentDiagnostic`。
- 必须继承完整受保护的手动TorqueChain/SB3/robust-zero/一拍PWM pipeline；CMake拒绝没有该保护配置的混搭。
- 复用已有IQ模式，绕过速度/位置环输出，IdRef=0，IqRef为本次选定的固定档位及方向。没有新造observer、滤波或电流控制器。
- 候选100/120/150/180/200/250mA，正负均可解析。每次仅允许一个人工命令、一个boot一次；无自动升档、反转、重试或故障清除。
- 沿用原200000us板端独立租约和约8ms外环二进制记录；到期由既有保护所有者关闭桥，任务清除诊断active并设IDLE/0A。STOP/故障/编码器过期/电流异常/超速优先停止。模式不能由普通START/RPC绕过准入。
- **当前直接Iq限幅仍为±0.20 A。0.25 A列为`LIMIT_BLOCKED`，不截成0.20 A冒充0.25 A，不消耗一次性请求。** 只有未来人工明确改变限幅后，250mA才可能获准；诊断绝不允许超过250mA。
- 本轮未修改任何PI参数、current/voltage limit、electrical zero、相序、encoder方向、CUR_CONFIRM、TWO_SAMPLE、PWM pipeline、hard protection或A/B启动逻辑。

## 手动入口（本轮没有发送）

需通过既有本地UART请求ID协议，且零点/健康/时序准入已正常完成。以下是**不同独立测试的选择示例，不是要连续执行的序列**：

```text
MOTOR TEST BREAKAWAY STATUS
MOTOR TEST BREAKAWAY POS 100 CONFIRM
MOTOR TEST BREAKAWAY NEG 120 CONFIRM
```

幅值单位为整数mA，只接受六个离散档位；不接受任意小数、扫角或电角偏移参数。`POS/NEG 250 CONFIRM`当前返回`ERR 109 LIMIT_BLOCKED`。旧`MOTOR TEST TORQUE ...`在此构建拒绝；原START也不能使能该模式。STATUS显示本次实际选定IQ_MA、LIMIT_MA、ID_MA=0、租约、USED/ACTIVE、SIGN及捕获TAG。完成后不能通过再发命令重启，需另一次人工安排的启动/校准。

入队时检查直接Iq限幅，正式功率准入前再次检查，避免选定值被破坏或超限后仍通桥。保留原抢占安全的规划和最终单一使能事务，不新增CCR/MOE/SD写入路径。

## 记录与身份

复用原32行、每行124B的启动记录及停机terminal，约200ms通常得到23–25个驱动帧。字段仍包含IqRef/Iq/Id、Vq/Vd、IU/IV原码、raw/filtered speed、机械角/电角、encoder raw/delta/dt/time、current path、PWM pending及CCR preload读回、门状态。**不是连续20kHz数据，也不是所有信号同时测量；不能检测采样间全部往返。**

均值/绝对均值、净位移、累计绝对位移、最大正/负偏移、FOC max/CCR late等在Python中计算，不在ISR打印或格式化。PWM applied仅预装载寄存器读回，不是门极或实际磁链/机械转矩证据。

新增4B捕获标记`breakaway_capture_tag=0x42574159`及实际编译直接Iq限幅的只读元数据；20B torque元数据保留本次幅值、sign、used/active。解码要求匹配完整Flash/BIN、ELF Reset_Handler、同次VTOR、SRAM中的新模式标记、已结束的单次状态。不会用旧50/100/200mA模式的捕获冒充本模式。

```powershell
# 只构建，不连接板子
cmake --preset BreakawayCurrentDiagnostic
cmake --build --preset BreakawayCurrentDiagnostic --parallel 6

# 默认只输出未测表，不会访问串口/调试器
python tools/breakaway_current_report.py

# 人工测试结束，通过既有受控捕获流程保存同次Flash/SRAM后，再离线解码
python tools/breakaway_current_report.py --elf <matching.elf> --ram <ram.bin> --flash <flash.bin> --vtor 0x08008000

# 每个报告保存到JSON后进行离线汇总；只读原始文件重新解码，不信任手改结论
python tools/breakaway_current_report.py --summary <pos100-1.json> <neg100-1.json>
```

工具没有刷写、串口、START、升流或写入补偿值的命令。每次结论在抓取后离线输出，如`Iq=+0.10 A -> STICK_SLIP`；不是在MCU ISR中执行浮点分类或自动决策下一档。

## 稳定起转判据

所有判读阈值明确放在`firmware_common/foc_breakaway_current_test.h`宏中，**只作用于离线诊断，不是生产保护阈值**：

| 条件 | 初值 |
|---|---:|
| 有效驱动帧 | 至少20 |
| 覆盖时间 | 至少180ms，驱动帧不得超出200ms租约 |
| 第一帧/相邻最大间隔 | 20ms / 16ms |
| 停机terminal记录 | 200–250ms，门关闭、IDLE、IqRef=0 |
| 正确方向净位移 | ≥3° |
| total_abs_travel / signed_net_travel | ≤1.20 |
| 运动区间中同向比例 | ≥80% |
| 全部区间中运动比例 | ≥70% |
| 最长静止间隔 | ≤40ms |
| 最后1/3窗口同向位移 | ≥0.50° |
| Iq均值误差 | ≤max(30mA, 目标幅值×25%) |
| Iq平均绝对误差 | ≤max(30mA, 目标幅值×30%) |
| Iq符号反向帧比例 | ≤10% |
| 记录的正常current path比例 | ≥95% |
| 其他 | 无饱和、有效编码器、无保护fault，FOC<50us、deadline/CCR late=0、actual margin>1us |

方向/静止判定的一LSB分辨率允许量为360/16384°；累计绝对路程不删掉小于LSB的角度差。净位移不足但持续缓慢前进可为`MARGINAL`；有往返、长停留或尾段不前进为`STICK_SLIP`；错误方向、明显不动、参考值被截断、数据不足、保护或时序失败分别单列，不能把没有fault等同于稳定起转。

只有全部条件同时满足才输出`CONTINUOUS_ROTATION`，含义仍是本短窗口降采样软件证据通过，不是独立转速计或转矩精度认证。特别是“开始跳动几度→随后停在一点”即使path/net=1，也因末段和静止条件不能通过。

## 最小值和建议补偿

- 正负方向分别统计，不平均。
- `observed_min_continuous_A`只是有一次通过的最小候选。
- `BREAKAWAY_IQ_POS/NEG`需同档至少3份不同新模式捕获全部通过，且所有更低候选至少各有3次记录；缺档、缺重复保持null。
- 按Flash+SRAM摘要去重，复制同一个捕获3份不能算3次；旧模式回放排除。CLI汇总会重新读取原始文件并解码，修改JSON中的分类不会改变结论。
- 正负阈值相差超过20%标记asymmetric，并保留两个方向结果。若需要单个工程建议值，以较大方向值加15%并向上取整到1mA，不取平均；另有分方向建议。
- `IQ_FRICTION_FF`若超出现有0.20 A限幅则保持null，另报告未限幅的建议值及`ff_limit_blocked=true`，绝不偷偷截断或写入正式控制/KVS。
- 例如“假设”测得某方向0.18 A，加15%为0.207 A，就超过当前限幅；这只是算法示例，**并非本项目测得0.18 A起转**。

当前真实最小值和FF均**尚未测得**。若最高可执行档0.20 A仍未通过，报告候选范围内未找到，不能推断0.25 A会成功或直接越过限幅。

## 已有真实记录的离线回放（非本轮实测）

| 旧记录 | 新判据回放 |
|---|---|
| +0.10 A，23帧 | STICK_SLIP |
| −0.10 A，23帧 | STICK_SLIP |
| 真正+0.20 A，23帧、净位移1.758° | STICK_SLIP：path/net1.675、运动比例约59%、尾段−0.066° |
| 上次请求0.20 A却被截为0.15 A | REFERENCE_MISMATCH |

回放文件：`tmp/breakaway-replay-pos100.json`、`tmp/breakaway-replay-neg100.json`、`tmp/breakaway-replay-pos200.json`；默认未测表：`tmp/breakaway-not-measured.json`。这些回放不会被汇总成新的breakaway测量，所有`BREAKAWAY_IQ_*`和`IQ_FRICTION_FF`仍为null。

## 构建和测试

| 配置 | Flash | RAM（含链接预留） |
|---|---:|---:|
| A BreakawayCurrentDiagnostic | 229332B | 130096B |
| B BreakawayCurrentDiagnostic | 228316B | 130080B |
| A 正式完整状态机、Breakaway关闭 | 228220B | 130080B |
| B 正式完整状态机、Breakaway关闭 | 227204B | 130064B |

**A诊断分区只剩44B Flash**，没有扩大分区、删保护或缩记录缓冲。未来加功能需重新检查链接余量，RAM Used不代表运行时堆/栈剩余。

A BIN SHA256 `eeee6ebcf7fd52f034075174d8fd54ad7985b68496526f25ce99e71dba3ec14d`，ELF `a0f9dbe85bf11c9a46a4b9da790481efa9d3f4ac7b9b7527f5da5e78b250d272`；B BIN `2172a00c215e9496dd042a43a1ae8c8aeabfa73a1d027f0d8637430aa676cae2`，ELF `4df3789629e2fab33d43c8309b644db7b0c67853a641dee2a7d23e4b0a8a6c13`。

关闭Breakaway的A/B完整状态机BIN哈希仍分别为`a4848c2e68723a04931ed395bc0a0bf177abf3648db52d484f69756eddf5e96a`、`f7becb511b0b19c6f164155a90e56a584883e993dbd126ba53a456d4c1587e9a`，与上一轮完全一致。新增模式的冻结FOC/encoder/PWM/protection函数一致，ADC timing/IRQ对象一致。只在任务级手动准入选择不同Iq值，没有新增20kHz ISR工作。

15项新诊断测试、44项既有扭矩回归通过。真实C单次准入owner在-O2/-Os执行，覆盖所有可执行档位/正负方向、250mA准入拒绝、不消耗请求、超过250/任意值拒绝、二次命令拒绝、200ms lease、STOP/fault/准备期间竞态、准入前篡改幅值拒绝。另覆盖末段停住/往返/错误方向/跟踪差/原150mA截断问题、缺失/延迟/非有限/缺关闭证据、匹配Flash/ELF/SRAM、重复捕获与不对称FF受限。

无新增编译warning/error；保留既有unused代码及RWX段告警。全仓库离线测试`python -m unittest discover -s tests`完成1296项、耗时314.948秒：1283通过，9失败、4错误；日志`tmp/breakaway-all-tests.log`。13个不通过方法逐名对比此前`tmp/torque100-all-tests.log`完全相同，无新增或消失项，均未为本轮强改旧断言。不能称全量全绿。全量运行期间补强的报告去重/源文件重解码等断言已在最终15项定向重跑覆盖，日志`tmp/breakaway-tests-final.log`；44项扭矩回归日志`tmp/breakaway-torque-regression.log`。

旧失败涉及早期源码隔离断言、历史映像尺寸/哈希等范围外测试，完整方法名和堆栈保留在日志，本轮不以“新增诊断通过”为由隐瞒它们。没有板测新版FOC max或CCR late，不复用历史28us结果冒充本模式实测。

本轮未执行任何板端操作，未改板上Flash或B启动选择，不声称外部操作后板端当前状态仍与上一轮相同。

breakaway-current diagnostic 已就绪，等待人工逐档上板测试
