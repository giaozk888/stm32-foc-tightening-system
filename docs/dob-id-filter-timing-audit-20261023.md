# Id波形—实际滤波—复位计时一致性审查

## 结论与范围

本轮仅代码、历史完整Flash/RAM及离线C验证，没有刷写/复位/运行硬件，没有改任何固件。
当前原B1047恢复状态不动。

**代码没有“Id连续超限20 ms才重置”计时器。20 ms是abs(Id)低通的时间常数，
滤波值超过50 mA立即清空DOB状态；恢复后重新累计约398 ms预热。**
如果要求的是“持续超限20 ms再重置”，当前实现不符合该意图，但不是us/ms换算错误。

稳态统计使用DOB刚更新后的同一abs_id_lpf，门槛两个宏均为`.05f`，不存在另算一条统计滤波。
现有日志缺连续原始/滤波/复位时刻三条同步序列，不能宣称已完成逐点实机波形一致性验收。

## 实际信号链

`MechanicalCurrent.id`是FOC的dq测量，经相干publication进入约1 kHz外环观察；
不是电机原始IU/IV ADC码，也没有保存每个20 kHz点。

代码路径：

1. `MechanicalDobMonitor_Observe`读取当前相干`c->id`。
2. `seconds = dt_us * 1e-6f`。
3. `k = seconds / (0.020f + seconds)`。
4. `abs_id_lpf += k * (fabsf(c->id) - abs_id_lpf)`。
5. 若`abs_id_lpf > .05f`，**当次调用立即**`MechanicalDob_Reset(..., DOB_MONITOR_ID)`。
6. 随后main的`IdSteady_Observe`拿到的就是`mechanical_dob_monitor.abs_id_lpf`、同次status/valid。

这是 `LPF(abs(Id))`，不是 `abs(LPF(Id))`。大幅正负交替可以signed mean接近0，
但LPF(abs(Id))仍明显为正；因此不能用-2.9 mA的signed mean去判断50 mA幅值门槛不应触发。
它也不是“每20 ms更新一次”或“20 ms矩形平均”。dt≈1 ms时k≈1/21，每次外环更新。

相关代码：

- `firmware_common/mechanical_dob_monitor.h`：20 ms与50 mA定义。
- `firmware_common/mechanical_dob_monitor.c`：更新abs滤波后立即判定/复位。
- `foc2_app_a/Core/Src/main.c`的`OuterObservation_Flush`：DOB观察之后将同一变量传给稳态统计。
- `firmware_common/id_steady_stats.c`：只统计持续时间，不控制DOB复位。

## 三种不同的“计时”不可混用

|项目|当前实现|是否控制DOB复位|
|---|---|---|
|20 ms|Id幅值与Iq匹配滤波时间常数|不作为持续超限确认时间|
|超限run_us，含5/20/100 ms分桶|IdSteadyOver的观测段时长/直方图|否，仅统计|
|observer.elapsed_s|2 Hz DOB复位后的预热累计|达到5/g≈397.887 ms才valid|

`MechanicalDob_Reset`把observer结构清零，含elapsed_s/initialized及内部滤波状态。
ID超限路径**没有清空外层abs_id_lpf或iq_lpf**，have_sample仍为1，幅值滤波继续跟随信号；
但在每一个仍超限的epoch再次将observer的预热时间清零。
降回阈值内后的第一次正常epoch只初始化observer，elapsed_s仍为0；
后续才累计seconds。因此1 kHz下恢复valid还包括一个初始化采样，不能把数学397.887 ms当精确硬件时刻。

其他样本/时序/序号等质量异常会额外清have_sample，下一次合格样本将Id幅值滤波seed为abs(Id)。
三次实测这些原因均0，不能用此路径解释本组三次的主要拒绝。

## 原C离线波形验证（不是实机波形）

新增独立host `tests/dob_id_filter_timing_audit_host.c`，直接链接未修改的实际
`mechanical_dob_monitor.c`与`id_steady_stats.c`，-Os/-O2均通过。
独立递推核对滤波值；核对门槛宏相同、同epoch门控、ID复位时elapsed_s为0及外层滤波不清零。

|合成刺激|实际C输出|说明|
|---|---|---|
|±60 mA每1 ms交替|LPF(abs Id)=60 mA；signed LPF最终幅值约1.46 mA；持续ID拒绝|两种滤波不可混用|
|40 mA背景，单个1 ms/300 mA脉冲|当次LPF(abs Id)=52.38095 mA，立即ID拒绝|没有等20 ms|
|同上脉冲消失后|ID拒绝共5个采样；第5 ms内恢复初始化；脉冲后约403 ms才再次valid|短脉冲可引起长不可用时间|
|10 mA背景，同样300 mA/1 ms脉冲|当次滤波值约23.80952 mA，无ID拒绝|不能说所有原始超限都重置|
|40 mA背景，每60 ms一个脉冲|脉冲组期间无法完成预热|损失受事件间隔影响，不仅取决于超限占比|
|恰好50 mA|无ID拒绝|代码严格`>`，不是`>=`|
|950/1050 µs交替dt|按实际dt递推一致，无时间/序号拒绝|未发现20 ms与µs换算错误|

合成完整CSV：`tmp/dob-id-filter-timing-SYNTHETIC.csv`，不能当成用户电机实测数据。
测试：`tests/test_dob_id_filter_timing_audit.py`；日志`tmp/dob-id-filter-timing-audit-tests.log`。
配套监控/稳态统计/decoder回归：`tmp/dob-id-filter-audit-regressions.log`。

## 历史实测资料核对

三次原始receipt见 `docs/id-steady-statistics-20261023.md`。
重新用`id_steady_report.decode`校验同session ELF/BIN/Flash/RAM hash、ABI、原保护/关断证据，三次均通过。
对应候选仍为BIN SHA256
`f76db9f86b4d3719f8d85349338b1ae8a3e3f0141aa0799700bda1638257b2b6`，固件未重建或改写。

三个1 s窗口filtered_bad_us均0，说明统计期间没有拿饱和/坏时序下的旧Id滤波值累计有效持续时间。
统计滤波超限时间为175.970/86.020/53.040 ms，段数14/11/4；
其中小于20 ms的滤波超限段分别11/10/3段，当前代码不会等这些段达到20 ms才处理。
全运行ID拒绝565/416/433，其他质量拒绝均0，与当前立即门控/反复预热的逻辑相容。

真实RAM稀疏帧也能看到两种现象：

|轮次|encoder sample_us|ADC seq|该帧Id [mA]|status/valid|
|---|---:|---:|---:|---|
|1|15293265|303536|+53.725|0 / 1|
|3|15294294|303554|+57.243|0 / 1|
|3|15747251|312615|+1.883|ID / 0|

“当前原始Id超过50 mA仍valid”和“当前原始Id很小却ID拒绝”并不自相矛盾，
因为门控看带历史记忆的LPF(abs Id)，不是该帧原始Id。
但该RAM frame没保存对应的abs_id_lpf数值，以上只是与代码相容，不能代替逐点滤波曲线核验。

## 目前不能声称完成的部分

- DOB ring只有末尾16帧，间隔至少64 ms，且未逐帧保存abs_id_lpf/elapsed_s/reset事件。
- Id稳态模块只保存1 s统计量及段时长直方图，没有连续Id数组。
- UART的IQLP_UA是**Iq低通值**，不是Id低通值；分条ADC查询也可能是不同epoch。
- abs_id_lpf只保留最终一个值，三轮分别34.555/22.423/20.242 mA；停机时observer已清零。
  不能据这些最终值反演此前20 ms波形与复位时刻。

若要最终实机逐点核验，需要另行准备同帧短窗trace：ADC seq/source时间、encoder时间、
Id_meas、abs_id_lpf、超限标志/持续时间、reset事件/原因、observer.elapsed_s和valid。
应从同一任务epoch二进制记录，不将稀疏串口输出插值成“原始波形”；本轮未修改采集固件或自动上板。
