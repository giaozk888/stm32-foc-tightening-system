# Id稳态统计候选与三次空载验证

## 不改变的部分

独立A配置 `MechanicalIdSteadyCandidate` 继承已审查的 `MechanicalDobShadowCandidate`，
仅新增 `FOC_ID_STEADY_STATS` task-only 观察统计，正式B未修改。
Id_ref仍为实际控制引用0 A；PI、S-curve、Ka=0.000046875 A/(rpm/s)、
摩擦前馈0.105 A、BEMF ψ=0.00034866 Wb、角度链、FOC/ADC/IRQ/PWM pipeline、
CUR_CONFIRM/CURRENT_INVALID和原保护均不改。
DOB仍只观察，0.05 A/20 ms Id域门槛、2 Hz与约398 ms预热及原复位策略不变。

## 统计窗口与避免选择偏差

- 固定+600 rpm空载，沿用原5 s驱动与原轨迹/减速/关断，三次独立复位采集，不升限幅。
- 仅用运动条件建立稳态：轨迹ref=600 rpm、abs accel_ref≤1 rpm/s、
  abs(speed_meas−ref)≤12 rpm连续500 ms，然后取**第一个固定1 s墙钟窗口**。
- 不用Id大小、DOB VALID或残差挑窗口。开始后速度超出范围也不重启选择窗口，单独累计unstable_us。
- 所有有限、时间/序号/发布来源合格的Id/Iq均进入统计，**包括Id超过0.05 A、DOB正在预热/被ID拒绝的样本**。
- 包括饱和样本，并单独累计voltage_sat_us、iq_sat_us；缺失数据不填0、也不跨缺口拼接超限段。
- 固定窗口没有完成或数据覆盖不足时保留并明确报告，不自动重试或改门槛；独立保护立即终止整组。

## 记录内容与定义

Id_ref、Id_meas、Iq、Id_error=Id_meas−Id_ref、speed：时间加权mean、mean abs、RMS、std、min/max。
Id_ref来自实际task读出的控制引用；本候选它固定0，不修改ADC发布或电流PI，Id/Iq仍来自同一次相干publication。

分别统计：

1. 未额外低通的dq abs(Id_meas)>0.05 A。
2. DOB实际使用的20 ms低通abs(Id)>0.05 A。

每种记录累计时长、占可观测时间比例、最长连续观测段、超限样本数、段数，
以及 <5 ms／5..20 ms／20..100 ms／≥100 ms 的段时长直方图。
第二种只在DOB实际更新过其Id滤波的epoch有效；因饱和/坏样本/坏时序未更新时，
单独计filtered_bad_us，不把旧滤波值冒充新值。
另记录正Id/负Id超限时长、abs Id幅值直方图和**全运行**DOB每种状态位的出现次数。
多状态位可同时累计，不能把它们强行相加成互斥分类。

统计在约1 kHz外环post-ACK执行，不是20 kHz ADC全量RMS。超限时长的分辨率约1 ms，
不能声称解析了更短的ADC毛刺；窗口边缘可能截断真实持续段，缺口会分段。
censored是右端因窗口/缺口/STOP而结束的段数，不包含左边缘未知起点的标记。

RAM新增336 B，无malloc/IRQ mask/ISR printf；只读`MOTOR TEST MECH IDSTATS CFG`及`... IDSTATS`，
沿用192-byte回复缓冲区，不增加线程栈。详细统计停机后从同session完整RAM解码。

## 文件

- 新增 `firmware_common/id_steady_stats.h/.c`、`id_steady_binding.inc`。
- 修改A main：独立全局统计与非控制观察尾部；protected task lifecycle与只读分派条件接入。
- A CMakeLists/Presets新增默认关闭的独立配置；B配置不加此选项。
- 新增 `tools/id_steady_report.py`、`tools/id_steady_board.py`。
- 新增 `tests/test_id_steady_stats.py`、`test_id_steady_report.py`、`test_id_steady_board.py`。

## 构建与验证

- A Flash215620 B、RAM130736/131008 B，静态余量272 B。未缩减堆或线程栈，板测必须核验实际栈和时序。
- A BIN SHA256 `f76db9f86b4d3719f8d85349338b1ae8a3e3f0141aa0799700bda1638257b2b6`。
- A ELF SHA256 `d5e8d1db65236ceb08932f87803c421491fda18a99a5851e3e581d961b14b6df`。
- B复编通过，BIN SHA256 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，逐位未变。
- A/B没有新增warning类型，历史unused/RWX warning仍在。
- 25项定向统计/DOB/脚本验证通过：`tmp/id-steady-targeted-tests.log`。
- 复核实际C在-Os/-O2下的均值/平方和/时长直方图、长偏移与短尖峰、缺口、饱和、
  时间回绕、STOP/fault冻结、无自动重新选择窗口、原始C结构到Python解析、协议极值容量。
- 预处理实际current/speed controller、encoder angle、power stage、ADC/guard、admission等函数未改；
  原DOB monitor目标对象和关键IRQ/ADC/encoder/zero/S-curve对象逐位一致。
- 相关完整回归结果记录于 `tmp/id-steady-regressions.log`。

## 板测凭据

用户确认断电/空载/防护后，仅暂存非活动A，两次完整回读通过：
`tmp/mechanical-ident-stage-1792718357409990300.json` PASS。
B/boot/config/private未变、activation=false、motor_commands=0、输出关闭、CPU halted。
随后单独请求用户确认上电/无报警/全程在场，预检通过才执行三次。

## 实测完成与恢复

完整相关回归247项通过：`tmp/id-steady-regressions.log`。
用户单独确认已上电、无报警、全程在场后，批次
`tmp/mechanical-ident-batch-1792718515172024000.json`采集3/3完成，无重试。

三次独立原始凭据：

1. `tmp/mechanical-ident-run-1792718515250179000.json`
2. `tmp/mechanical-ident-run-1792718558816020500.json`
3. `tmp/mechanical-ident-run-1792718588959215500.json`

三轮均完整采到第一个固定1 s窗口，current与filtered-current数据覆盖率100%，
无序号/时间/数据缺口，窗口内电压饱和和Iq命令饱和均为0。
但是**只有第2轮全程在±12 rpm定义内**；第1、3轮窗内分别47.997/157.999 ms超出该速度范围。
因此是“三次空载匀速命令下的完整固定窗”，不是“三次严格全程稳定”的成功验收。
不丢弃第1/3轮，不重选更好窗口，也没有追加运动凑三次合格。

|统计（每窗1 s）|第1轮|第2轮，严格稳态|第3轮|
|---|---:|---:|---:|
|Id_ref mean/min/max [mA]|0/0/0|0/0/0|0/0/0|
|Id_meas mean [mA]|-0.665|-2.907|-2.917|
|mean abs Id [mA]|41.969|37.689|36.550|
|Id RMS [mA]|78.781|61.092|62.227|
|Id std [mA]|78.778|61.023|62.158|
|Id min/max [A]|-0.904685/+0.603571|-0.536191/+0.872902|-1.170442/+0.443859|
|Iq mean [A]|0.213775|0.219186|0.219439|
|Iq RMS [A]|0.230911|0.232988|0.230902|
|Iq std [A]|0.087295|0.079000|0.071849|
|Iq min/max [A]|-0.949588/+0.859101|-0.309603/+1.334734|-0.114130/+0.898407|
|speed mean [rpm]|597.485|599.904|596.854|
|speed std [rpm]|4.802|2.331|5.676|
|speed min/max [rpm]|578.845/605.678|593.936/604.930|573.869/605.451|
|speed越界时长 [ms]|47.997|0|157.999|

这里min/max是约1 kHz相干观察点的测量极值，不是命令限幅；0.50 A是Iq**命令**限幅，
不能误称它保证每个瞬时测量点≤0.50 A。当前未有原始ADC/角度的对应逐点trace，
不能仅由这些极值断言是真实电流尖峰、采样毛刺还是角度链瞬态。

## 0.05 A超限持续时间

|统计|第1轮|第2轮|第3轮|
|---|---:|---:|---:|
|未额外低通abs Id超限总时间 [ms]|264.143|243.057|234.045|
|占1 s窗口比例|26.4143%|24.3057%|23.4045%|
|最长连续观测段 [ms]|5.000|3.002|3.002|
|超限段数|193|197|193|
|段直方图：<5 / 5..20 / 20..100 / ≥100 ms|192/1/0/0|197/0/0/0|193/0/0/0|
|正Id超限时间 [ms]|120.039|88.038|95.807|
|负Id超限时间 [ms]|144.104|155.019|138.238|
|DOB实际20 ms滤波abs Id超限总时间 [ms]|175.970|86.020|53.040|
|占1 s窗口比例|17.5970%|8.6020%|5.3040%|
|滤波值超限最长连续段 [ms]|52.955|29.944|26.045|
|滤波值超限段数|14|11|4|
|滤波段直方图：<5 / 5..20 / 20..100 / ≥100 ms|5/6/3/0|6/4/1/0|1/2/1/0|

第3轮有1个未额外低通超限段在窗口右端被截断，其完整物理时长未知。
绝大多数未额外低通超限是1..5 ms短段，滤波abs值超限仍有4..14段/秒；
按现有策略每次都会重置DOB并要求约398 ms重新预热。
这说明“短时波动→模型Id域拒绝→长预热”的放大作用实际存在；
不能只把5.3%/8.6%/17.6%当成DOB最终无效率，因为随后预热还会占用时间。

## 全程DOB原因已区分（不只是末尾ring）

|约8 s整轮统计|第1轮|第2轮|第3轮|
|---|---:|---:|---:|
|观察总数|7880|7970|8020|
|VALID|1127|866|527|
|有效率|14.3020%|10.8657%|6.5711%|
|ID拒绝|565|416|433|
|WARMUP|5577|6055|6408|
|ZERO_SPEED|611|633|652|
|CURRENT/TIME/SEQUENCE/SATURATED等其他拒绝|0|0|0|

本组三次的直接质量拒绝全部为ID，其后大量WARMUP；不是ADC源丢失、时间/序号不连续或保护停机。
各轮有效率变化不能被解释为本次“统计功能改善/恶化控制”，本轮未改门控，也不是受控ON/OFF实验。

## 时序、保护、栈与原B

- FOC wall max依次33.235294/33.317647/33.317647 µs，deadline miss与CCR late全0。
- 最小实际CCR余量15.182353/15.182353/13.441176 µs。
- first fault全0，encoder timeout/DMA error/schedule miss/control stale均0。
- CUR_CONFIRM enter/clear/fault：138/138/0、162/162/0、153/153/0。
- 整轮保存的MotorCtrl最低已观测空闲栈：2520/2548/2548 B。
- 新统计自身wall max=92/51/49 µs，含IRQ抢占，为1 kHz任务额外计算，不是20 kHz FOC耗时。
- outer trace最大entry gap1106/1100/1096 µs，core196/193/199 µs，observe195/196/194 µs。
  不把不同epoch的最大值相加。
- 三轮停止后均ANALOG SAFE、SD/MOE/CCER关断、完整Flash/RAM保存、CPU halted。

用户确认12 V关闭后，恢复凭据
`tmp/mechanical-ident-restore-1792718646428222500.json` PASS：
原B/boot/config/private不变，B应用未运行，motor_commands=0；
最终VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted。未再运行电机。

## 基于这组数据能判断什么

1. 不支持“存在约50 mA恒定dq Id偏置”的说法：Id_ref=0，而signed Id均值只有-0.7..-2.9 mA。
   主要表现为较大的双向波动/尖峰，mean abs 36.5..42.0 mA，RMS61..79 mA。
2. 不能据此排除相电流原始偏置或角度误差：旋转变换可能让相偏置表现为零均值交流，
   dq闭环自洽也不证明物理电角零点正确。三次同方向统计无法把这些原因唯一分离。
3. 优先补尖峰前后的同帧ADC/Id/Iq/角度/时序证据，判清真实电流波动与测量/变换异常；
   不凭mean接近0就跳过电流反馈链，也不直接重标electrical zero。
4. 同时已经有直接证据审查DOB质量门控/恢复策略：50 mA靠近当前mean abs Id背景，
   4..14次/秒的滤波超限会反复抹掉2 Hz观察器状态。不能简单把signed mean小等同于abs域永远合格。
5. 本轮不自动调偏置/角度、提高50 mA、缩短预热或接入Iq；这些需要下一轮有针对性的方案和验证。
