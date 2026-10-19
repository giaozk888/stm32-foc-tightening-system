# 固定 ±0.10 A 扭矩链诊断准备

本轮只有源码、离线构建和文件回放；不刷板、不复位、不改变启动选择、不启动电机。此前+50mA仅约0.154°净位移且往返，本轮不据此改PI、相序或电角零点。

## 模式与入口

复用默认关闭的 `FOC_TORQUE_CHAIN_DIAG`，新预设为 **TorqueChain100mADiagnostic**（A/B各自目录）。它继承完整受保护的SB3、TWO_SAMPLE、CUR_CONFIRM、robust zero admission、一拍PWM pipeline和现有超速/故障链。

```powershell
# 只构建，不触碰硬件
cmake --preset TorqueChain100mADiagnostic
cmake --build --preset TorqueChain100mADiagnostic --parallel 6
```

- Iq只允许固定 +0.10A 或 −0.10A，IdRef固定0。
- 通过 `MotorControl_SetIq` 进入原 MOTOR_MODE_IQ；该分支不设置run_speed_pi，不运行速度PI或位置控制求解，但沿用原电流PI、Clarke/Park、SVPWM和PWM pipeline。
- 每个boot只接受一个手动请求，约200ms后由原独立TIM7/ADC commit准入链停止。STOP、故障、数据超时和超速仍优先关闭输出。
- 保留原零点校准、正常健康确认复位、neutral commits和时序/编码器/电流预检。失败不自动重试；普通START/RPC不能代替该诊断准入。
- 不自动先正后反，不在一次通电中自动重复。反向必须是另一次人工选择并通过正常预检的测试。
- **100mA构建只接受ZERO，拒绝PLUS5/MINUS5及任意角度偏移命令。** 保持electrical zero=10507、encoder direction=−1、10极对数，三相与IU/IV映射不变。

为后续人工上板准备的命令如下，本轮未发送任何一条：

```text
MOTOR TEST TORQUE STATUS
MOTOR TEST TORQUE POS ZERO CONFIRM
MOTOR TEST TORQUE NEG ZERO CONFIRM
```

命令需按既有本地UART协议加请求ID。STATUS应显示 `IQ_MA=100 ID_MA=0 LEASE_US=200000 PERIOD_US=8000`。不能凭旧50mA profile的STATUS代替。

`FOC_TORQUE_CHAIN_IQ_MA`默认100，编译只接受100与显式历史50；150或任意数值会被CMake/头文件拒绝。历史 `TorqueChainDiagnostic` 预设显式保留50，历史+50mA镜像、收据、只允许正50mA的验收脚本不冒充新版。**本轮不会增加0.15A模式或自动升级电流。** 若±0.10A仍不足，只建议另行人工评估后做±0.15A小步进对照。

## 记录和统计

复用原32行/124B `cl_startup` 缓冲，约8–9ms一帧，覆盖约200ms驱动窗口并保留终止帧。记录包含：

- IqRef、Iq、Id、Vq、Vd、原码IU/IV；
- encoder raw、delta、dt、timestamp、机械角、电角及预测电角；
- raw/filtered speed、validator/current_path、模式与门状态；
- PWM pending三路、source sequence、CCR1/2/3预装载寄存器读回。

不增加20kHz ISR格式化或UART输出。统计在Python对已保存文件计算，不作为保护或控制输入。

元数据使用原20B结构末尾的2B填充保存 `iq_mA=100`，无需扩容大缓冲。旧50mA捕获该位置为0；解码时明确标记历史幅值，不能用新幅值重标旧数据。

```powershell
# 下列只读已有文件，不会连接串口/调试器
python tools/torque_chain_decode.py --elf foc2_app_a/build/TorqueChain100mADiagnostic/foc2.elf --sram <匹配的SRAM.bin>
python tools/torque_chain_decode.py --trace-bin <cl_startup.bin> --sign -1 --offset-deg 0 --iq-ma 100
```

保留mean Iq、mean Id、mean |Iq|、mean |Id|、Id/Iq绝对比值、Iq平均绝对误差、平均速度、Vdq、正反向区间。新增：

| 字段 | 精确定义 |
| --- | --- |
| net_mechanical_travel_deg | 最后一帧机械角−第一帧机械角；兼容旧mechanical_travel_deg |
| total_absolute_travel_deg | 相邻帧机械角差的绝对值之和；**不使用方向计数的LSB死区** |
| max_positive_excursion_deg | 相对第一帧的最大正向偏移，至少0 |
| max_negative_excursion_deg | 相对第一帧的最小负向偏移，至多0（有符号） |
| max_negative_excursion_abs_deg | 上项负向幅值的非负形式 |
| directionality_ratio | sign×净位移/累计绝对位移；无运动时null，不伪造0或1 |

统计基准是首个已记录的**驱动帧**，不是通桥前的独立基线；停机后terminal帧不参与驱动统计。以上是抽取采样下的位移/路程，不能声称是高频连续机械真实路程；采样间来回会漏记。PWM applied仍是CCR预装载读回，不是门极或绕组电流独立实测。

## 人工判读目标

分别比较正/负Iq下的角度序列、净位移、累计路程和正负偏移：单向运动应具有与命令一致的位移方向；若累计路程明显但净位移很小、有正负往返，则是振荡/微动证据，而不是稳定转动。ratio只提供证据，没有新加入控制判据或阈值。

Id均值及mean |Id|应与Iq一起看，不能仅凭一帧或仅凭Id≈0证明物理磁链对齐。Iq跟踪、角度连续性和未饱和仍不能替代扭矩仪或物理相序验证。未确认前不换相、不改零点/方向、不调PI、不提高现有限幅或保护阈值。

## 本轮验证

新100mA A/B链接成功：

| 槽 | Flash Used | RAM Used | 分区Flash剩余 |
| --- | --- | --- | --- |
| A | 229044B | 130096B | 332B |
| B | 228028B | 130080B | 1348B |

RAM Used包含链接预留，不代表运行时堆/栈剩余。未增加采样缓冲容量、扩大分区或删除保护来通过链接。

A BIN SHA256：`cfca08dbe56ffd3a997bdeff841471c1b4e9b2d876169f3ca99171dfeba137ea`；ELF：`2a292b0bcf268794bbe2758b2f7641e5e786af53374a828e1798d3d5f4992af4`。

B BIN：`860f910ee6225e9c5da04a9a6ef29a03f51f687b0196d61a36ac5eb8e0a53ff1`；ELF：`8d72f4eaffb528d9dd04c85598fe97c2db952ad1d0bbb43316dd4bcc9e2fbb01`。

另重建A/B RundownGuardTrial、RundownDiagnosticTrial、历史TorqueChainDiagnostic，共8个相关构建通过。历史50mA A/B BIN/ELF哈希与此前板测完全一致；正常构建无诊断宏。新100mA与既有诊断构建的warning集合一致，没有新增编译warning/error，既有未使用代码、第三方和RWX段告警仍在。

18项扭矩相关定向回归通过：实际C生产准入/任务owner分别按50、100mA在-O2和-Os编译执行；正/负固定命令、IdRef0、单boot一次、200ms lease、STOP/故障/准入竞态拒绝；100mA拒绝偏移及150mA；正向、反向、往返、静止、亚LSB累计路程、终止帧排除、元数据ABI和CLI幅值选择。冻结FOC/保护函数预处理内容及ADC timing/IRQ对象一致。既有rundown隔离测试另3项通过。

仅文件回放此前50mA的23帧：净位移0.153809°，累计绝对位移1.384277°，相对首驱动帧最大正偏移0.263672°、最大负偏移0°，方向比1/9。最大负偏移为0不意味着没有反向移动（仍有5个反向区间）；它只表示未回到第一帧基准以下。这验证新统计能揭示往返，但**不是100mA新实测**。

全量`python -m unittest discover -s tests`运行1240项：1227通过，9失败、4错误，312.300s。13个不通过方法逐名对比与之前完全相同；本轮未修改这些旧断言或处理范围外问题，因此不能称全量全绿。日志`tmp/torque100-all-tests.log`。全量启动后新增的CLI幅值用例已包含在最终18项定向重跑中，全部通过；最后`git diff --check`通过。

只改变诊断Iq定值、诊断状态显示/幅值标记、构建开关和离线统计/测试。current/speed PI参数、phase order、encoder direction、electrical zero、Clarke/Park、SVPWM、PWM pipeline、CUR_CONFIRM、TWO_SAMPLE、过流/超速/故障阈值均未改。

本轮没有硬件操作，新100mA版本没有实测结果。仍停在原B启动选择、输出关闭的此前现场状态，等待人工上板；未通过本轮命令运行或恢复任何固件。
