# Electrical zero / angle chain：离线诊断准备

本轮只审计代码、跑离线测试、编译候选。**没有连接串口/调试器，没有刷板、复位、改启动选择或启动电机，正式 B 未修改。**
最后已知板端状态沿用上轮恢复的 B709、输出关闭/MCU 停住；本轮未重新测量板端状态。

基线：固定 +0.35 A / 5 秒反馈 Iq 平均约 0.334 A，但用户肉眼未见实际旋转。编码器报告约 +3.2° 后基本停住，不能把这个读数当成独立证实的机械旋转。暂停升流和调速度 PI。

## 1. 代码审计

| 环节 | 当前实现 | 能否由代码证明 |
|---|---|---|
| 编码器 | AS5047P，16384 counts/rev，SPI 帧奇偶校验 | 软件接口与换算可证明；实轴/磁铁装配需现场确认 |
| 机械方向 | `ENCODER_DIRECTION=-1`，raw 减小为软件正向 | 软件方向可证明，顺/逆时针依观察端定义 |
| 机械解绕 | `AS5047P_Delta14(new,old)`，跨 0/16383 取短差；累计方向化机械角 | 离线跨界、正反向验证 |
| 极对数 | `POLE_PAIRS=10` | 代码配置如此，手拧软件比例不能独立证明实际磁极对数 |
| 电角零点 | `ELECTRICAL_ZERO_RAW=10507`，编译期常量 | Git 初始导入已有此值；未找到与当前接线对应的物理 d 轴对准证据 |
| 电角函数 | `wrap[-Delta14(raw,10507) * 10 * 2π / 16384]` | 相当于带固定相位偏移的机械角 ×10，方向与机械累计角一致 |
| 预测角 | 已有控制速度→电角速度，补偿 DMA 样本 age，并由 ADC 周期继续预测 | 本轮不改；手拧检查主要观察实测电角，而非用预测误差代替零点 |
| IU/IV | PA0 ADC1_IN1 → U；PA1 ADC2_IN2 → V；沿用当前电流反馈符号 | 代码映射清楚，物理 IU/IV 与绕组 U/V 必须现场核对 |
| Clarke/Park | α=Iu；β=(Iu+2Iv)/√3；Id=αcosθ+βsinθ；Iq=−αsinθ+βcosθ | 数学符号自洽；不代表真实磁链方向已知 |
| 逆 Park / SVPWM | α=Vdcosθ−Vqsinθ；β=Vdsinθ+Vqcosθ；U/V/W 电压经原 SVPWM | 本轮数学完全未改 |
| PWM 相位 | CCR1→U（PC0/PB13），CCR2→V（PC1/PB0），CCR3→W（PC2/PB1） | 软件端可证明，线束/驱动板/实际绕组对应需实机确认 |

结论：没有找到可直接据此修改相序、方向或零点的软件符号矛盾。硬编码零点是否仍正确没有证据，不能擅自更改。
正 Iq 是按上述软件正机械方向定义的转矩需求；它在实物上能否产生同向转矩，仍取决于磁零点与物理相位匹配。

## 2. 两种独立、默认关闭的构建

### 输出关闭的手拧版

`ElectricalAngleHandDiagnostic`：`FOC_ANGLE_CHAIN_DIAG=1`、`FOC_ANGLE_HAND_ONLY=1`。

- `LatestOriginal_Admit` 的功率使能事务编译掉；偏移命令与普通 START 不能通过该诊断入口开启功率。
- BEGIN/READ/END 只在已有校准通过的 unused READY、IDLE、SD=0、MOE/AOE=0、CCER=0、无故障时允许。
- 仍沿用原 ADC/编码器/软件健康保护。输出关闭不等于驱动板传感器供电关闭；未来上板校准仍按原正常供电流程。
- 手动慢转一个有标记的机械整圈，再反向回到起点；不要高速手拧触发原有速度/编码器保护。本轮没有执行该动作。

任务在每个接受的约 1 kHz 编码器更新后观察：

1. `encoder_raw`；
2. 独立按 raw 短差累计的机械 counts，以及原控制代码的 `encoder_position_deg`；
3. 实际 `encoder_theta_e` wrapped 值；
4. 对**实际电角函数输出的相邻 wrapped 差**做解绕、累计电角，非简单把机械角乘 10 作为所谓实测电角。

观测摘要跨完整手拧窗口累计；每 20 ms 保存一帧到 12 帧有序小 ring，序号最后发布。
单帧 28 B；ring 只覆盖约 240 ms，采集器必须及时排空。读到被覆盖的帧明确报错，不沿用旧帧或假补点。
格式化只在低优先级命令任务；ADC ISR、编码器 ISR 不新增记录/打印。

诊断 PASS 要求：到达至少 ±16384 counts 的机械整圈、返回初始 ±128 counts 范围内、有正反方向、无数据/门极异常；实际电角累计与机械累计×10 最大偏差 ≤2 electrical deg，原机械位置与 raw 累计偏差 ≤0.1 mechanical deg。
这些只是诊断一致性门槛，不是任何运行保护阈值。
错误极对数、反向符号、半圈混叠、丢失/延迟数据、门极开启、非有限角度等离线情况均不能 PASS。

**PASS 只证明软件角度链一致性，不是磁链 d 轴零点或物理 pole count 校准。**

### 人工单偏移候选

`ElectricalZeroOffsetDiagnostic`：独立目录，启用角度诊断，关闭 HAND_ONLY。

- 只有七个固定命令可选：−30、−20、−10、0、+10、+20、+30 **电角度**。
- 每次 IdRef=0、IqRef=+0.35 A、速度/位置环 bypass，持续最多 **400000 us**。
- 直接 Iq 限幅仅该候选显式为 0.35 A；不把正式默认从 0.20 A 改掉。
- 必须在**本次启动**先完成输出关闭手拧 BEGIN→END PASS，才能提交某一个 offset。
- 每启动只允许一个 motion admission，停止/故障后不可重新排队；不实现自动扫点、连续变角或自动升流。
- offset 只存在本次诊断 RAM 中；不改 `10507`，不写 KVS/Flash，不提供 SAVE/自动选零点。
- 先把选定 offset 用于原电角转换，等待现有 fresh encoder 更新，再通过原保护 admission 进入固定 IQ 模式。
- 保留现有过流、超速、encoder stale、CURRENT_INVALID、CUR_CONFIRM、独立健康关断、一拍 PWM 和时序检查。

32 帧 schema-2 任务 trace，每至少 12 ms 保存，覆盖约 0.4 秒窗口并保留终止/故障帧。
记录 IqRef/Iq/Id、Vq/Vd、IU/IV raw、encoder raw/timestamp/delta、机械角、电角、速度、pending/applied preload、判别状态及门极状态。
另复用完整任务级运动统计：net / total absolute raw encoder travel / 最大正负 excursion；绝对路程包含编码器量化抖动，不冒充实际轴路程。
原 timing/fault 快照保留。连续性、转矩效率与最佳零点都需未来实测分析，不预选候选。

## 3. 未来人工工具（本轮均未运行现场模式）

手拧版手工部署、校准与输出关闭预检通过后，可用：

```powershell
# 默认仅输出离线计划，不打开串口
python tools/angle_hand_collect.py

# 未来人工明确开始的手拧采集，不含刷写、复位或电机启动命令
python tools/angle_hand_collect.py --collect --outputs-off-confirmed --port COM5 --seconds 20
```

在采集窗口内，按轴上标记慢转一整圈并反向回到起点。
采集器只实现读状态、ANGLE BEGIN/READ/END 与安全停止白名单；不接受 OFFSET、Iq、START、FW BEGIN 或 RESET。
ring 超出、门极/数据异常或 ACK 不明会结束采集并保留日志，不自动补采。

原协议命令为：

```text
MOTOR TEST ANGLE BEGIN
MOTOR TEST ANGLE STATUS
MOTOR TEST ANGLE READ <seq>
MOTOR TEST ANGLE END
```

`READ` 的 MC 是机械累计 counts，MMDEG 是原机械位置解绕毫度，EMDEG 是实际电角函数解绕毫度，WRMDEG 是 wrapped 电角毫度；US 为相对采集时间。
收齐所有有序行和 END 后 STATUS，再离线解码：

```powershell
python tools/electrical_angle_report.py --hand-log tmp/angle-hand-<id>.log
```

手拧通过后，未来使用偏移候选也要先在同次启动完成手拧 PASS。
然后人工只选择例如：

```text
MOTOR TEST ANGLE OFFSET +10 CONFIRM
```

其他选择严格写为 `-30`、`-20`、`-10`、`0`、`+10`、`+20`、`+30`，没有任意数字或 sweep。
每点须有单独授权和电源/保护预检，保持 0.35 A、400 ms；本轮不执行。
捕获同次 BIN/ELF/Flash/RAM 收据后，文件解码器支持 `--offset-receipt ... --elf ... --image ...`，输出 Iq/Id/Vdq、位移、正负 excursion、timing、fault，不自动选择新零点。

## 4. 编译与隔离

| 候选 | Flash | RAM | RAM 区剩余 |
|---|---:|---:|---:|
| A Hand | 223380 B | 130328 B | 680 B |
| B Hand | 222364 B | 130312 B | 696 B |
| A Offset | 224660 B | 130400 B | 608 B |
| B Offset | 223644 B | 130384 B | 624 B |

四个镜像均链接通过，RAM 余量很小；本轮未扩大 trace/堆、不声称已做板端 stack high-water 验收。

BIN SHA-256：

- A Hand：`68ef9fdc565476b5da8af0c511e564874d324c7bf4d6c4200bdd2443d86173bf`
- B Hand：`9a54a6f21b3613fe9beb4f8c6173f35bf9f799fd076abd0551ea7c083b297f3d`
- A Offset：`e5eccb535bebf645e6148e8b14cf2cba83bcae9d78453f7ddd4c53bd97670e04`
- B Offset：`9a38c5ed119d189463d511eb512a56ef4ceae5576638c7dbc1146fdfad26ddf0`

预处理对比确认 PI/Clarke/Park/SVPWM、CURRENT_INVALID/CUR_CONFIRM、timer guard、PWM entry/stage 及编码器处理函数均未改。
只有 offset 候选的直接 Iq clamp 为获准的 0.35 A，以及诊断 angle wrapper 增加人工选定偏移；手拧版电角函数与原版完全一致。
ADC timing / IRQ 对象与原候选逐字节一致；没有加快/改频、调优先级或关闭保护。
编译保留原基线 12 条 unused 警告与 RWX 链接警告，无新增类别；本轮新增诊断初期编译问题已修正，不留错误。

新增角度诊断/文件解码/手拧采集白名单回归 10 项通过；包含真实 C observer、实际 owner、全部七点解析、400 ms lease、未手拧禁止 offset、单次 admission 与 HAND_ONLY 编译禁用功率。
相关既有回归另有 torque-chain 44、350mA 9、speed500 7、breakaway 40、脚本日志 14 项通过；连同新增角度诊断 10 项，共 124 项定向回归通过。

全仓离线 discover 的一次运行记录为 **1348 项、18 failure / 4 error，非全绿**，日志在 `tmp/angle-chain-all-offline-20261019.log`。
该全仓运行收集测试时，角度诊断模块还是 8 项，最后新增的手拧采集器 2 项随后单独通过；不能把它描述为最终源码的原子全绿验收。
未通过项涉及旧源码字面断言/内核哈希、旧镜像或本地证据文件、旧状态机/派生默认宏解析、Python/C 仿真预期等；本轮不为使这些测试绿而改控制算法或历史阈值。
例如源码正则直接取第一个 `MOTOR_SPEED_IQ_LIMIT_A` 会误把默认关闭的 0.50 A 候选分支当作正式默认，而本轮预处理比较确认手拧候选的原控制参数不变。
新增角度定向测试没有失败；全仓遗留/基线问题仍须另行整理，不能宣称全部离线测试通过。

结论：手拧及人工单 offset 诊断已就绪，等待人工上板验证；没有以编译/离线 PASS 代替真实角度链、物理相位或磁零点验收。
