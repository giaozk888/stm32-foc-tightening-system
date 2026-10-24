# 手动Ka=2.79e-5候选实测（2026-10-22）

用户明确选择上次50ms拟合正斜率作为试验值，并不是辨识质量通过。
本轮只执行一次ON，未自动扫增益、重复试验、修改PI或正式B。

## 镜像与流程

- A preset：`Ka279ManualTrial`，继承原加速度前馈审计配置，使用48槽日志池、通用单元测试关闭。
- Ka固定初值0.0000279 A/(rpm/s)，最大accel_ref200 rpm/s，对应5.58 mA；保留原审计开关，脚本不发送GAIN命令。
- 240 rpm、Iq±0.50 A、摩擦0.105 A、BEMF OFF、原S-curve/current/speed PI与全部保护不变。
- 原8秒rundown/12秒lease、300 rpm独立超速和20000°行程不变。
- BIN213004 B，RAM链接125152/131008 B；没有缩任务栈/RTOS heap。
- BIN SHA256 `7891e9ce9b2aec45b74019b5a63a908ff236bfbafb0c24caf693244d1a984c27`。
- ELF SHA256 `a978c8b4a893cd91c6837923931665a158f3f91d439e087fea43c6e701cdf97a`。

用户分别确认12V关闭、上电无报警/在场/.5A后按原流程执行。
stage：`tmp/ka279-stage-1792659037606052500.json`，两次完整回读，B/boot/private不变，未提前激活。
run：`tmp/ka279-run-1792659138395940300.json`，start_attempts=1，无自动重试。
完成原约8秒空载运行，RUNDOWN_TIMEOUT、CONTACT=0/FLT=0，不是实际拧紧OK。
完整Flash/RAM/BIN/ELF同轮身份校验，16个审计帧及8000次速度更新统计保存。

## 实际前馈与保护

- effective_ka=2.789999962e-5，实测max accel_ref199.999756 rpm/s。
- max iq_ff=0.005579993 A，占0.50 A限幅1.115999%。
- sign_errors/zero_ff_errors/formula_errors/sync_errors均0。
- 8000 trajectory_updates /8000 enabled_samples；统一PI+FF+friction求和/限幅审计通过。
- saturation/aw_limited/unexpected_aw_samples均0。
- pi_ff_opposed=148次：制动或超调时允许PI与前馈反向，不能单凭此计数认定方向错误。
- FOC max32.60 µs，deadline miss=0，actual CCR late=0，actual min margin15.164706 µs。
- CUR_CONFIRM121 enter/121 clear/0 fault；无独立保护故障。
- 零点4000 valid/45 reject/4045 total/max连续reject1，zero1561/1564，PASS。
- 启动前MotorCtrl栈余量2504 B。
- UART丢字节0；同轮RAM读取日志池dropped_pool/dropped_full/dropped_uart均0。

## 效果：只作历史参考，不冒充严格A/B

参照上一轮Ka=0：`tmp/ka-full-run-1792658234874784900.json`。
两次独立启动、不同诊断负载（完整采集 vs 前馈审计），每条件仅一轮；没有重复性/因果改善证明。

|指标|上一轮Ka=0|本轮Ka=2.79e-5|
|---|---:|---:|
|全参考加速段MAE rpm|15.225|14.140|
|匀速MAE rpm|3.827|3.813|
|超调 rpm|5.870|6.011|
|Iq命令峰值 A|0.374|0.389|
|积分器峰值 A（UART截断值）|0.103|0.067|
|任务观测Iq瞬时峰值 A|1.183|1.112|
|stable-motion确认延迟 ms|334|225|
|Iq饱和时间 ms|0|0|

加速MAE描述性下降1.085 rpm，约7.13%；超调增加0.141 rpm，Iq命令峰值增加0.015 A。
stable-motion延迟不是物理起转时刻，也不是选择Ka的核心指标。
任务瞬时Iq峰值不等于持续电流；不以均值掩盖该观测。
本轮结论是“该试验值可在原保护下运行，单轮历史对比有改善迹象，尚未确认优于0”。
Ka仍为用户手选的未标定参数，不能把上次低R²/窗口翻号问题当成已解决。

如需继续比较，下一轮应在同一审计镜像、相同诊断负载下，用原FF ON/OFF开关交错重复，
以完整参考加速段time-weighted |speed_ref−speed_meas|为主，另看超调、Iq峰值、积分器及饱和。
必须另行人工授权并确认现场状态；本轮不自动追加测试。

## 编译与离线测试

新候选编译通过，仍13条既有unused/RWX警告，无新增warning/error。
Ka系列45项（包含手动候选3项）及speed系列81项，共126项通过。
覆盖固定增益读回、原受保护START所有者、保护不重试、默认不访问硬件、
历史比较不得标严格A/B，以及控制/协议函数预处理相同。

修改：A CMakePresets新增显式候选，`tools/ka279_board.py`、`tests/test_ka279_board.py`及本文。
没有改动任何固件控制函数、保护阈值或正式B。

## 收尾

用户确认12V关闭后，仅恢复原B启动选择：
`tmp/ka279-restore-1792659231533240400.json` PASS。
generation991、confirmed B、pending=0；B仍227964 B、CRC627317606。
B/boot/private应用数据未变，停在B入口、B应用未运行、motor_commands=0。
VTOR0x08040000、DHCSR0x30003、SD0/BDTR0/CCER0、CPU halted。
不再启动电机，试验Ka未写入正式B或持久化配方。
