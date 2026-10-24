# 完整加速段 Ka 实测（2026-10-22）

## 结论

一次240 rpm空载状态机已完成；记录从起转到参考加速结束、再到匀速的完整2.55秒。
240个连续约10ms窗、2551次约1kHz任务观测，flags=0、read_failures=0。
数据采集、关断及实时性通过，**Ka辨识质量未通过**，没有自动应用Ka、翻符号、调PI或扫增益。
完整数据不等于一次单轨迹闭环试验必然得到可靠惯量系数。

## 固件与采集方式

新独立A preset `KaFullAccelerationDiagnostic`，继承空间优化正常候选。
Ka=0、FRIC=.105 A、BEMF OFF、240 rpm、Iq±.50 A、300 rpm独立超速、
20000°行程、原8秒rundown和12秒lease保留，保护/控制参数/IRQ均未改。
全程约8秒正常运行，空载自然RUNDOWN_TIMEOUT、CONTACT=0/FLT=0，不是拧紧OK。

BIN211960 B，SHA256 `5bf45ca701767f0d4b8c98bd7188167a09b24eddb9be341a4a19f11a76c84c0b`。
ELF SHA256 `0120c4208ba2d0b85e3249b26e504105f901d10141fa92cced0b85ded1878a83`。
RAM链接130016/131008 B，余992 B；没有缩heap/任务栈/保护缓存，完整记录仅诊断构建存在。
MotorControlTask编译器局部帧328 B、ADC IRQ184 B、KaFull_Observe88 B。
这些不是完整最坏调用链或运行期高水位保证。

ADC侧沿用已经验证的20 B版本化电流快照，仅DWT/整数/原值发布。
约1kHz任务的**每次观测**参与10ms窗积分，并非每10ms只取一个瞬时Iq。
每窗24 B、240窗5760 B，加112 B header，ABI5872 B；满窗冻结，停止后完整RAM回读。
不打印逐点UART、不改变Monitor周期、不增加实时ISR格式化或动态分配。

每窗含：实际时间间隔、ADC序号差、电流来源与encoder时间差、task年龄、
累计raw机械增量、平均Iq/摩擦命令、平均LPF(Iq−friction)、滤波实测速度端点、
同周期speed_ref/accel_ref端点、样本数、全窗质量flags。
窗内任一观测异常会累积flags，不以均值吞掉质量标志。
原始约1kHz逐点电流不完整保留在RAM，所有20kHz ADC原始样本也没有完整保存。

实际每窗以encoder时间差达到至少10000us结束，故本轮总窗长2.55秒，
不是假定所有窗正好10ms；积分、差分和回归使用实际时间。
encoder时间为SPI接收、current source为已有ADC软件读取时间，不是模拟采样孔径的仪器测量。
完整采集不等于整个8秒的原始全速录波；本轮参考加速在1403.02ms结束，
捕获末端speed_ref240 rpm、speed_meas241.48 rpm，已覆盖完整参考加速和后续匀速。

## 流程与原始证据

- 原B983基线：`tmp/ka-sync-motion-restore-1792656303784481500.json`。
- 用户确认12V关闭/空载固定/全程在场后，非活动A暂存：
  `tmp/ka-full-stage-1792658142307034700.json`，两次完整回读、B/boot/private/metadata未变，未激活。
- 用户另行确认12V开启/无报警/.5A/在场后，一次运行：
  `tmp/ka-full-run-1792658234874784900.json`，start_attempts=1、automatic_retry=false。
- 同版本BIN/ELF/整Flash/整RAM哈希及载入地址验证通过。
- 文件解码/拟合复核：`tmp/ka-full-first-fit-review.json`。
- 原始240窗与50/100ms分组的所有accepted/rejected均保存在回执/复核JSON。

## 实时性、安全与日志

|指标|实测|
|---|---:|
|FOC max|32.97647 µs|
|deadline miss / actual CCR late|0 / 0|
|actual CCR min margin|14.63529 µs|
|发布片段max|81 cycles / .47647 µs|
|CUR_CONFIRM|113 enter /113 clear /0 fault|
|零点|4000 valid /37 reject /4040 total，max连续reject1，zero1559/1564，PASS|
|启动前MotorCtrl已测栈余量|2524 B|
|UART丢字节|0|
|新48槽日志池 dropped_pool / dropped_full / dropped_uart|0 /0 /0|
|全参考加速段MAE|15.225 rpm|
|匀速MAE|3.827 rpm|
|超调|5.870 rpm|
|Iq命令峰值|.374 A|
|任务观测Iq瞬时峰值|1.183 A|
|Iq命令饱和|0 ms|

日志池丢弃计数由本轮RAM和同版本ELF符号读取，未更改LOG STATUS文本协议。
任务瞬时Iq峰值不是持续电流，不能用平均值代替或掩盖此观测。

240个窗端点的current source相对encoder为120..279us，平均231.64167us；
task读取时current年龄25..80us。它们不是每窗积分的独立物理采样孔径证明。
和旧63ms短窗属于不同一次运行，不能把两轮时间差差异单独解释为固件延迟恶化。

## 拟合：不按stable、残差或结果符号挑点

公式：

```text
mean(LPF20ms(Iq_measured - Iq_friction_command))
    = Ka * (filtered_measured_rpm_end - filtered_measured_rpm_start) / actual_seconds + b
Ka单位 A/(rpm/s)
```

诊断电流使用与速度相同的variable-dt 20ms LPF；只写诊断副本，不参与反馈。
窗口积分用实际dt，净电流LPF采用梯形积分。
固定连续5窗（约50ms）为主拟合，10窗（约100ms）为敏感性复核。
沿用固定低速准入：两端实测速均至少10 rpm；其它方向/静摩擦区和flags坏窗明确列为rejected。
不按t_stable截断，不按残差删点，不自动选择最优延迟或改符号。

|分组|有效窗|Ka|b A|R²|残差RMS A|
|---|---:|---:|---:|---:|---:|
|约50ms|38|+2.7940794e-5|.04950724|.338097|.01185936|
|约100ms|18|−2.2279937e-5|.05470163|.106391|.00839833|

不能只取50ms的正数写入前馈。原因：

- 主拟合R²=.338，低于沿用的.6质量门。
- 残差与速度相关系数+.693，超过沿用的.5门；常量摩擦命令+截距不足以解释全部数据。
- 第9组约50ms窗占最大杠杆.607：滤波测速85.31→11.27 rpm，
  实际差分−1396.09rpm/s、mean净电流LPF−.002501 A。
  这只是记录到的急减速/测速变化，未证明必然来自真实粘滑或编码器问题。
- 换成约100ms分组，斜率翻为负值；不能把它解释成负惯量或自动反转Iq方向。
- 50ms留一法范围+1.44678e-5..+3.36391e-5，表明对单窗较敏感。

因此`candidate_ka=null`、`next_ab_multipliers=[]`、`parameter_writes=false`。
正向整体机械运动与正电流并不保证同一启动阶段的电流/加速度满足单一线性惯性模型。
后续应考虑已稳定转动后的独立多档小幅加减速与速度相关负载分析，而非继续重复同一起转
或按残差挑出让Ka变正的点。本轮没有实现/执行新轨迹或任何增益测试。

## 编译与离线验证

- 新A编译通过，13条既有unused/RWX警告，无新增warning/error。
- 新完整记录/拟合/板测包装器6项：C -Os/-O2、已知Ka、时钟/序号回绕、
  质量标记、冻结/reset、未覆盖/负斜率不可标定、原START所有者、确认门及保护不重试。
- Ka系列合计42项、speed系列81项：123项通过，新6项包含在42项内。
- 原同步BIN/ELF重新编译哈希保持原值，不改旧回执。
- 控制/保护/协议函数预处理比较：仅排除新被动观测调用/发布统计目的地址后相同。
  PI、S-curve、采样、PWM及IRQ数学/调用次序未更改。

主要新增：`firmware_common/ka_full_diagnostic.h/.c`、`tools/ka_full_report.py`、
`tools/ka_full_board.py`、`tests/ka_full_host.c`、`tests/test_ka_full_diagnostic.py`、
`tests/test_ka_full_board.py`；仅A的main/CMake/preset和诊断binding加入显式默认OFF分支。

## 最终关断与恢复

采集后SD/MOE/CCER关闭、MCU停住；用户确认12V关闭后，仅恢复原B启动选择：
`tmp/ka-full-restore-1792658376155300100.json` PASS。
generation987、confirmed B、pending=0；物理B仍227964 B /CRC627317606，
B/boot/private应用数据保持不变，停在B入口，B应用未运行。
VTOR0x08040000、DHCSR0x30003、SD0/BDTR0/CCER0，恢复motor_commands=0。
没有自动追加电机运行或把本轮不可信Ka写入正式控制。
