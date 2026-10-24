# Ka=2.79e-5 固定五轮实测（2026-10-22）

## 范围与证据

用户授权当前配置重复5次，并分别确认12V关闭、上电无报警/.5A/全程在场。
仅同一Ka279ManualTrial镜像；不升流、不切增益、不改PI/轨迹/保护，不追加第6轮。
目标240 rpm，Iq限幅±.50 A，Ka=0.0000279 A/(rpm/s)，摩擦.105 A，BEMF OFF。
每轮重新启动、校准、原时序/栈/保护预检后，仅一次原START。
均自然空载RUNDOWN_TIMEOUT、CONTACT=0/FLT=0，不是实际拧紧OK。

原B991基线：`tmp/ka279-restore-1792659231533240400.json`。
准备：`tmp/ka279-repeat-stage-1792660337812225300.json`，两次完整核验，无需重刷，
flash_programming=false，B/boot/private/metadata不变，尚未激活，motor_commands=0。
批次：`tmp/ka279-repeat-batch-1792660521657071500.json`，5/5完成，每轮1 START。

BIN SHA256 `7891e9ce9b2aec45b74019b5a63a908ff236bfbafb0c24caf693244d1a984c27`。
ELF SHA256 `a978c8b4a893cd91c6837923931665a158f3f91d439e087fea43c6e701cdf97a`。
各轮同版本Flash/RAM/ELF身份及原B保持验证通过。

## 逐轮结果

|轮|加速段MAE rpm|匀速MAE rpm|超调 rpm|Iq命令峰值 A|积分器峰值 A|stable-motion延迟 ms|
|---|---:|---:|---:|---:|---:|---:|
|1|14.731|3.614|5.757|.440|.142|420|
|2|13.279|3.474|6.328|.422|.133|434|
|3|17.406|3.685|6.357|.422|.082|261|
|4|13.183|3.886|6.518|.401|.127|348|
|5|11.348|4.174|7.202|.371|.115|260|
|均值|13.9894|3.7666|6.4324|.4112|.1198|344.6|
|样本SD|2.25583|.27193|.51777|.02638|.02330|83.42|

核心评价取完整参考加速段time-weighted |speed_ref-speed_meas|，不按stable-motion确认时刻截断。
stable-motion不是物理起转时刻。第3轮确认早但加速误差最大，不能据延迟更短就判断更好。
第5轮加速误差最低，但匀速误差与超调最高；不只挑最好一项作为总体改善证明。

原settling判据：只有第2/4轮有结果5593/7551 ms，另3轮未满足。
不能把缺失设成0或报告“全5轮平均settling6572ms”；6572ms只是有结果2轮的均值。
五轮任务观测Iq瞬时峰值1.270/1.184/1.301/1.349/1.340 A，非持续电流；原硬保护不变。

## 前馈、时序与保护

- 实际前馈峰值各轮约5.57999 mA，占.50 A限幅1.116%。
- 每轮8000个速度更新、16个审计帧，Ka/符号/零加速度归零/公式/同步检查均0错误。
- Iq saturation=0 ms，aw_limited/unexpected_aw各0。
- FOC最大（跨五轮）32.95294 µs，deadline miss总0，actual CCR late总0。
- actual CCR最小余量（跨五轮）13.82353 µs。
- CUR_CONFIRM共562 enter/562 clear/0 fault。
- UART丢字节各0；同轮RAM日志池dropped_pool/dropped_full/dropped_uart各0。
- 每轮关断SD/MOE/CCER关闭、MCU halted证据完整后才开始下一轮；无保护故障恢复或重试。

## 结论边界

可确认该手选Ka在这五轮原保护条件下可运行，前馈/限幅实现正常，时序没有退化到deadline。
加速误差范围11.348..17.406 rpm，SD约2.26 rpm，重复启动波动明显。
没有同期OFF组，不能把相较历史单次Ka=0的差异证明为该Ka的因果改善。
历史Ka=0单轮15.225 rpm，与本批均值的差约1.24 rpm，小于本批SD；这不构成统计显著性检验。
不会将未通过辨识质量的Ka自动标记为已标定，更不会自动写正式B。
若用户后续要求因果对比，应同镜像OFF/ON交错重复，以加速误差为主并同时约束超调/Iq峰值。
本轮没有追加这种对照。

## 文件与离线验证

新增五轮包装器`tools/ka279_repeat5.py`和4项`tests/test_ka279_repeat5.py`。
复用原单轮、confirmed-A reset/calibration/preflight/START/STOP所有者，没有固件变化。
候选/五轮脚本7项测试通过：精确5轮、无第6轮、保护不重试、确认门、默认只读文件、
混合Ka拒绝、缺失settling不作0、原控制实现保持与手选值准确读回。

逐轮回执：

- `tmp/ka279-repeat-run-1792660521699303500.json`
- `tmp/ka279-repeat-run-1792660565583997700.json`
- `tmp/ka279-repeat-run-1792660595944989200.json`
- `tmp/ka279-repeat-run-1792660626323757700.json`
- `tmp/ka279-repeat-run-1792660656577842900.json`

## 收尾

用户确认12V关闭后，使用实际最后一轮回执仅恢复原B启动选择：
`tmp/ka279-repeat-restore-1792660747794505000.json` PASS。
B/boot/private未变、confirmed B、无pending，SD/MOE/CCER关闭，MCU停在B入口，
B应用未运行、恢复motor_commands=0，不再运行电机、不写入新Ka。
