# 正常状态机制动器负载：同镜像 DOB OFF 对照

用户请求关闭DOB再试一次，并确认12V关闭、MCU供电、制动器释放、
固定有防护、接线未变、12V／限流0.5A、全程在场可立即断电。
仍使用固定制动器在防护外独立施加／解除，不接触旋转件，先轻载。

## 同镜像和唯一变量

固件与上一轮ON完全相同：正常预设 `TighteningDob025`。
BIN223880B，SHA256
`0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5`；
ELF SHA256 `53642f7a942df34ecb6df41efac7324f22f9534b360c3c0a59df2c500a0adaa7`。
不重新构建、不修改任何固件，保留Ka0.000046875 A/(rpm/s)、摩擦0.105A、
BEMF0.00034866Wb、PI／S-curve／PWM／采样／编码器／保护。
普通240rpm START，原300rpm trip／20000度／8秒rundown／12秒lease、
总Iq+/-0.50A、原11.95秒host STOP；不SET/SAVE配方、不强制CONTACT。

只在功率关闭／空闲时发送 `MOTOR TEST MECH DOB FB OFF`，要求实际CFG
先为默认ON、GAIN_PPM250000，再OFF确认和第二次CFG ON0。估计器仍
观察，仅补偿不接Iq；运行中验证ON0／FEEDBACK0／COMP_UA0，停机RAM
要求enabled0、peak0、comp0。不同状态不假冒有效OFF对照。
OFF只在RAM保持；MCU复位仍恢复正常默认ON，不修改正式软件默认。

## 主机检查

`tools/dob025_normal_fsm_board.py` 增加显式 `--dob-off` 与
`--baseline-restore`：运行ON/OFF必须匹配已独立回读的stage计划；
恢复B则继承实际run选择，不因忘传OFF而更改硬件模式。
首先核验上一轮正常ON后的实际B1107恢复证据
`tmp/dob025-normal-restore-1792741405427869500.json` 及其完整Flash，
不能用更早B1103冒充当前板状态。
阶段程序发现完全相同A时不擦写，仍两次完整Flash回读、保留B/boot/config。
需另行上电无报警确认，准入／校准／时序／任务栈通过才一次START。
任何保护、通信或关断异常停整轮，不自动重试。

新增OFF切换／回读／其他前馈不变和停机零峰值检查，原模拟CONTACT
仍继续、只START一次；正负IqRef结构化字段回归保留。
定向回归结果及实际stage/run/restore证据后续追加。

## 对比边界

上一轮ON记录 `tmp/dob025-normal-run-1792741325539315300.json`：
约8.8秒自然OK，DOB峰值25mA、cap1048更新、总Iq峰值0.50A、
速度段累计饱和0.854006s、最大正超调43.66864rpm，
FOC max33.18824us、deadline miss0／CCR late0，无独立保护故障。
前次负载精确施加／解除时刻与制动力矩没有同步通道。
本次尽量复现原过程，但人工制动重复性未标定，不能拿两个不同负载
事件直接给出DOB提高X%的因果结论；更不能把CONTACT后原FSM主动停速
和TIGHTEN/HOLD固定电流的时间算成速度跟踪失败。

## 同镜像 OFF 计划核验通过，尚未启动

37项／7模块定向回归全部通过：
`tmp/dob025-normal-off-regressions.log`。
阶段 `tmp/dob025-normal-stage-1792741880273681200.json` PASS：
完整镜像一致，无需重刷（flash_programming=false）；两次完整回读通过，
B／boot／private／metadata未变，OFF计划已记录，activation=false、
motor_commands=0、输出关闭／CPUhalt。等待独立上电无报警确认。

## OFF实际测试完成

用户独立确认上电／无报警／全程在场后，执行一次普通START REQ7841。
`tmp/dob025-normal-run-1792741938493316700.json` PASS；原始UART
`tmp/dob025-normal-off-run.log`，完整停止Flash/RAM已保存。没有重刷、
重试、SET/SAVE或保护参数变化。
校准4000有效／49拒绝，连续最多1，零点1560/1563，任务栈free2532B。
功率关闭的实际CFG从默认ON1，经唯一OFF命令回读ON0，再次CFG确认ON0；
GAIN_PPM仍250000。加速度FF／摩擦／BEMF均保持原ON及原值。
运行中全部采到的FB STATUS均ON0／COMP_UA0，停机RAM enabled0、
comp0、peak0、GOOD/HOLD/FADE/CLAMP0。GOOD0是关闭的**反馈适配器**计数，
不表示旁路观察器整体没有有效估计，也不把OFF当成质量故障。

以主机START发送为起点的状态观察：

|约时间 s|观察|
|---:|---|
|0.11|RUNDOWN_START，PRECHECK已通过|
|1.01|RUNDOWN、armed=1|
|约4.0--4.95|CTRL大部分在227--243rpm，尚未CONTACT|
|5.15--5.55|IqRef500mA；CTRL131.5→21.8→5.6→2.6→6.1rpm|
|5.43|CONTACT_CONFIRM pending1、confirmed0|
|5.61--5.62|CTRL回升286.4rpm，CONTACT_CONFIRM退出回RUNDOWN、confirmed0|
|约5.73--6.54|回到约230--242rpm附近|
|6.85--7.12|再次降速87.4→3.1→0.9→0.5rpm，IqRef500mA|
|6.96|第二次CONTACT_CONFIRM，尚未确认|
|7.19|CONTACT1，进入原停止确认，MODE=IDLE、IqRef0|
|7.42|TIGHTEN，armed1／confirmed1，依次80/100/120/150mA|
|8.62|HOLD150mA|
|9.15--9.16|本次REQ的COMPLETE RESULT=OK，STATUS OUTCOME=OK、IDLE PREV=DONE|

第一次短时制动候选没有变成已确认CONTACT；速度恢复后返回RUNDOWN。
后续持续低速负载自然确认并完成原FSM。不强制CONTACT、未新增堵转操作。
结束时CONTACT在IDLE可清零，以同REQ的COMPLETE和IDLE PREV=DONE证据为准，
不因末次CONTACT0误报失败。

## ON／OFF两次观察，不是标准化负载A/B

|指标|上一轮ON|本次OFF|
|---|---:|---:|
|完整流程自然终止|OK，8.798s|OK，9.150s|
|加速段MAE rpm|12.73924|12.84179|
|参考匀速段MAE rpm，包含制动和接触停速过程|35.43853|35.12395|
|全速率统计正超调 rpm|43.66864|51.35574|
|总Iq命令峰值 A|0.50|0.50|
|速度段Iq饱和累计 s|0.854006|0.759974|
|最长连续饱和 s|0.411963|0.409008|
|速度积分器峰值 A|0.265352|0.130820|
|实际DOB补偿峰值 mA|25|0|
|FOC max us|33.18824|33.18824|
|deadline miss／CCR late|0／0|0／0|

OFF速度段参考峰值约240+51.36=291.36rpm，未触发原300rpm独立超速，
但已较接近其门槛；不能为得到更大数据而放宽保护。
OFF最小PWM提交裕量15.11765us；独立FAULT VALID0／FLAGS0，
CUR_CONFIRM enter/clear164/164、fault0；最后UDROP/UERR/RXDROP0。
统计里的原始Iq_measured峰值不是命令峰值或已验证物理电流峰值，
不据此声称总Iq命令绕过0.50A限幅。

本次OFF采到的掉速／解除反弹更强，加载明显不与上一轮同时刻同幅度：
不能按最小速度、8.8与9.15秒完成时间、51.36与43.67超调，直接计算
DOB改善百分比。参考匀速MAE含负载和CONTACT时低速，不当作纯空载
匀速稳定性指标；TIGHTEN/HOLD后的主动停速已排除在速度统计之外。
结论仅为同镜像ON/OFF均能完成本次自然流程、OFF确实零补偿，尚不能
据这两个手动加载样本判定DOB独立抗扰收益或真实拧紧转矩精度。

## 物理断电后恢复原B

用户单独回复“关了”后执行恢复，
`tmp/dob025-normal-restore-1792742057460705600.json` PASS：
原B／boot／config／private保持，B应用未运行，motor_commands0；
metadata1111选择原B，VTOR0x08040000、SD/BDTR/CCER0、CPUhalt。
无额外运行。OFF仅本次RAM选择，正常软件默认DOB0.25 ON未改。
