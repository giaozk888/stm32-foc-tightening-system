# 五个启动时刻：同镜像连续六轮

用户要求连续六次观察，同一0.25倍Ka、不混入上一轮数据，不改固件或控制参数。

## 计划和核验

- 镜像StartupTimestampsDiagnostic，BIN221716 B，SHA256
  `c2fb66e8710f6ff92295cfe8201ce050173c1d96e9a7a598f0260ed393319108`。
- B963停止基线：`tmp/startup-times-restore-1792649182262901700.json`。
- 两次完整OFF核验：`tmp/startup-repeat-stage-1792649633748257500.json` PASS，
  flash_programming=false、activation=false、motor_commands=0，B/boot/private/metadata不变。
- 固定Ka=0.000046875 A/(rpm/s)，BEMF OFF，FRIC ON/0.105 A，240 rpm、Iq±0.50 A。
- 保护和原配方不变：独立300 rpm超速、20000°行程、8 s rundown、12 s lease。
- 原START每轮一次，重新校准/预检、输出关闭时设置/回读GAIN=25；
  真正保护或关断/证据失效停止整组，不重试、不补跑。
- 五个时间均用板端共同1 MHz时基，按t0归一化；原START_MS保留回溯定义，
  t_stable是50 ms条件确认事件。时标精细并不等于1 us的实际物理起动测量精度。
- `tools/startup_timestamps_repeat.py`默认只读文件；显式OFF/ON/恢复三入口。

## 离线验证

本轮只改主机固定六轮编排/统计，相关18项离线回归通过，
包含精确六轮无第七轮、保护或时间证据失败停止、不混增益、不二次换算ms、缺失值/标准差及默认无设备访问。
日志：`tmp/startup-repeat-tests.log`。

## 实测结果

批次`tmp/startup-repeat-batch-1792649702871346200.json` PASS，6/6全部采完，
每轮原START一次、8000点速度聚合；五个事件valid=31，压缩同seq、UART和RAM均一致。
全部空载自然RUNDOWN_TIMEOUT、CONTACT=0/FLT=0，不能写成实际拧紧OK。

### 启动时刻，相对每轮t0（ms）

|轮|t_Iq|t_motion确认|t_speed首次过阈值|t_stable确认|旧START_MS回溯起点|
|---|---|---|---|---|---|
|1|62.939|75.569|69.937|368.062|318|
|2|61.985|76.482|69.938|120.026|70|
|3|61.987|78.581|73.983|436.043|386|
|4|56.983|423.497|70.982|451.991|402|
|5|52.942|73.430|71.983|464.987|415|
|6|58.984|78.580|70.982|424.047|374|
|均值|59.303|134.357|71.301|377.526|327.5|
|样本标准差|3.836|141.663|1.522|130.521|130.528|

每轮t0归一化为0；五个时间统计均n=6/无缺失。
连续位移窗口起点分别为65.538/66.482/67.572/413.490/62.434/68.570 ms，
其后满足窗口跨度和净位移要求才锁存t_motion。
六轮运动确认方向均+1，未将反方向运动藏进均值。

### 判读边界

- Iq命令≥10 mA出现52.942..62.939 ms，首次测速abs≥2 rpm为69.937..73.983 ms，变化相对小。
- 五轮连续位移确认73.430..78.581 ms，第4轮423.497 ms；该较晚轮原样保留，未删除离群值。
  t_motion均值受到第4轮显著影响，不能只报134 ms而不展示原始六轮。
- 第4轮的早期测速过阈值仍不等于满足16净counts/≥4次增量/10..50 ms等连续位移证据。
  因此不能声称第4轮在423 ms前完全没动，只能说之前未满足当前诊断确认标准。
- t_stable范围120.026..464.987 ms，除第2轮外均在368..465 ms才确认；
  主要波动出现在初次反应以后持续建立运动的阶段，不是一个固定300~400 ms的命令处理延迟。
- t_stable是原≥2 rpm连续50 ms的确认，不是达到240 rpm并稳定跟踪的时间。
  旧START_MS回溯到成功连续段起点；两者约差50 ms符合定义，未增加50 ms控制延迟。
- 本组只有同一Ka，无同期OFF；不能仅凭本组确定摩擦、初始转子角、零点或PI中的哪一项是根因，
  更不能宣称0.25倍已最优。本轮不自动调参、不追加试验。

### 其余指标

|轮|加速MAE rpm|匀速MAE rpm|
|---|---|---|
|1|14.693|3.616|
|2|16.366|3.361|
|3|12.424|3.165|
|4|12.885|3.367|
|5|14.457|3.765|
|6|12.809|3.386|
|均值±样本SD|13.939±1.511|3.443±0.213|

Iq命令峰值均值0.41383 A、最大0.444 A；总Iq饱和0 ms，AW limited/unexpected均0。
FF峰值约9.375 mA，sign/zero/formula/sync错误均0，BEMF电压前馈始终0。
超调均值6.3957±0.5967 rpm；settling只有3/6有效，均值7452.67 ms，未将另外3个缺失值填0。

### 实时性与证据保存

- FOC wall最大33.06471 us，deadline miss=0，actual CCR late=0，最小actual margin14.400 us。
- CUR_CONFIRM717 enter/717 clear/0 fault，最大2 cycles；encoder timeout/DMA/schedule/stale全0。
- MotorControlTask预检栈余量2512..2548 B，保留原至少256 B门。
- 全组六轮UDROP=0，无token解码错误。每轮完整Flash/RAM哈希校验通过，原B/boot/private均未变。

六轮回执：
`tmp/accel-gain-run-1792649702930263800.json`、
`tmp/accel-gain-run-1792649747319596700.json`、
`tmp/accel-gain-run-1792649777826794500.json`、
`tmp/accel-gain-run-1792649808306646200.json`、
`tmp/accel-gain-run-1792649838818759300.json`、
`tmp/accel-gain-run-1792649869301260000.json`。

用户确认12 V关闭后，仅恢复原B启动选择，不再运行电机。
恢复回执`tmp/startup-repeat-restore-1792650012377333500.json` PASS：
确认B、pending无、generation967，SD/MOE/CCER关闭、MCU停在B入口；
B应用未运行、motor_commands=0，原B/boot/private未变，完整Flash哈希核验通过。

追加真实六轮保存数据回归：重新解码六份RAM/Flash、检查压缩同seq匹配及summary统计一致，未访问设备。
