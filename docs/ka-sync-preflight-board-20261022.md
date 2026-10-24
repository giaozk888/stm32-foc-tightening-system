# 同步采集候选 A：输出关闭上板预检

本轮只校准和功率输出关闭的FOC计算/时序预检，没有START、没有电流注入或转动测试。
没有把本轮结果说成“运动中时间对齐已通过”或“已辨识Ka”。

## 停机基线与暂存

首次stage在Flash写入前发现CPU未halt，与原B975入口停机记录不符，故中止。
安全收尾关闭输出、停住MCU，没有写Flash或激活A。
只读核验：`tmp/ka-sync-readonly-1792655243531601800.json`，完整Flash等同原基线。
用户明确“重试”、12V保持关闭后，重新reset并在原B入口断点停住：
`tmp/ka-sync-reposition-1792655338510022900.json`，Flash未变，B应用未在该次reset后运行。

仅更新非活动A，stage `tmp/ka-sync-stage-1792655362896946400.json` PASS：
两次完整回读，B/boot/private/元数据未变，activation=false、motor_commands=0。
镜像与离线候选一致：BIN219100B、SHA256
`5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136`。
ELF SHA256 `f00c940b6f868f4c1f4c88c028db23742dd7c33412ddac3a516256da17b68ed3`。

## 试运行

用户确认12V开启、无报警/.5A/在场后，仅一次正常A/B试运行。
boot健康5s自动确认及reset按既有流程完成，没有强制确认、优先级或保护修改。
run `tmp/ka-sync-run-1792655465337102800.json` PASS。

|项|实测|
|---|---:|
|FOC wall max|31.28235us|
|deadline miss|0|
|actual CCR late|0|
|actual min margin|14.90588us|
|快照发布片段max|80cycles = .47059us @170MHz|
|MotorControlTask栈余量|2524B|
|CUR_CONFIRM|48 enter /48 clear /0 fault|
|START次数|0|
|同步短窗采样点|0（预期）|

零点valid4000、reject42、total4045、max连续reject1、zeroU1560/V1564，PASS。
total包含尚未准入/窗口启动的样本，不把4000+42与4045的差异说成数据丢失。
无first fault，READY/USED0/SD0/MOE0/CCER0，未消耗运动lease。

同一轮完整Flash/RAM身份验证通过。ADC侧电流快照发布有效偶数版本：
version262910、source_seq156045、source_us7920562、published_us7920579。
该次发布距ADC pair软件时间17us；不是电流与机械运动的最终对齐误差。
快照Iq=-.106731A只是功率关闭时的一个瞬时读数，不能据单点判断电机正反转或惯量。
机械短窗count=0，因为始终IDLE；数据缺失在此是预期，不伪造64个有效运动点。

## 收尾

预检后STOP/ANALOG SAFE、SD/MOE/CCER关闭，MCU停住。
用户确认12V关闭后，只恢复原B启动选择并停在B入口：
`tmp/ka-sync-restore-1792655544439211500.json` PASS。
B/boot/private未变、B应用未运行、motor_commands=0，不再试运行。

新增板测包装器 `tools/ka_sync_board.py` 默认仅文件验证；显式OFF staging、
ON无START预检、OFF恢复分开。`no_motion`始终抛错，不具备运动采集入口。
3项包装器离线测试通过，覆盖确认门、START禁令、时序/栈/快照不完整拒绝。

下一阶段仍需要人工授权的原安全边界空载运行，才能采到约1kHz的64点短窗，
再判断电流source与encoder时间差、同LPF与原始位置变化关系。
