# bounded-current-reject 版 Rs50：一次复测

## 授权与准备

用户确认 12 V OFF、MCU ON、轴由台架机械夹具锁住、外壳固定/防护、原动力/
IU->PA0/IV->PA1/PC6->CTRL_SD 接线、12 V/0.5 A、在场可立即断电。
仅复测一次 Rs50，不自动进入75/100mA、Ld或Lq。

新增 `tools/motor_ident_reject_board.py` 独立精确核验新 BIN/ELF/1660B ABI
和已恢复 B808 基线；复用旧 RS50 准入/自动确认复位/保护流程。
原 runner 只新增默认禁用的 extra readout/decode hooks 和 ABI 参数，旧默认1596B
与精确镜像身份未被替换。新 wrapper 校验 REJECT_MAX=16/RUN_LIMIT=3，停机后才读
REJECT/REJECT ROW，RAM/线载荷一致性核验。3 项新 mock 测试和4项原runner测试通过。
没有改固件控制、阈值或异常预算；没有通过更改旧 SHA 绕过验证。

## 实测

- OFF 暂存及独立完整回读 PASS：`tmp/motor-ident-rs50-stage-1792497885596679200.json`。
  B/boot/private/metadata 未变，尚未激活时才通知用户上电。
- 用户单独确认12 V ON、无报警、可立即断电。
- Run：`tmp/motor-ident-rs50-run-1792497935803403400.json`。
- A 正常5秒健康确认及复位完成，FW CURRENT=A、CONFIRMED=A、PENDING=-、GEN=811。
- 前置校准/保护/profile/filter/timing/stack 通过，才单次发送
  `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`，明确收到 QUEUED ACK。
- excitation_attempts=1，START=0，无重试，无后续阶段。
- 终态 MODE=RS /STATUS=ABORT /REASON=8（MID_TIMING），N=0。
- reject=0、good=1、run=0、max_run=0、first_valid=0。
  **本次不是0.20A单点/连续/累计越界退出，也没有首次电流越界帧可展示。**

start_us=7982291；第一次被辨识参考owner接受的 sample source_us=7982297、
seq=157280；安全停止 cl_stop_us=7982365，即 admission 后约74us已停止。
远未达到200ms后的Rs稳态窗口，不能计算Rs。

## 退出的含义和证据边界

MID_TIMING由当前辨识自己的以下检查之一触发：
1. normal accepted pair seq delta !=1；
2. normal accepted pair的软件时间戳delta不在45–55us；
3. task duration+1ms cap。

此次开始后74us即退出，排除400ms+1ms task cap；因此是1或2。
触发时的失败 seq/dt 没有独立锁存，最终RAM只保留上一对的last_seq/last_us；
不能从停机后shadow更新过的cl_frame倒推出哪一项，也不能虚构该帧的dt。

这不等于FOC >50us，也不等于硬件ADC漏采：original ADC TIMING MISS=0/PF=0，
原 first_fault valid=0、live保护无fault、encoder valid。
源码中frame.source_us来自ADC处理内的软件时刻，发生在入口pending/CCR处理之后。
启动首拍empty pending与下一拍实际commit的耗时差，**可能**造成软件时间戳delta
不在45–55us；此外原discriminator拒绝帧也会造成normal accepted pair有gap。
这些是待区分原因，不宣称本次已经确证哪一个。后续应先保存失败seq/dt及相关
pipeline/validator前态，再决定Rs与L瞬态质量门如何分工，不直接改原保护或放宽阈值。

时序：FOC max=30.788235us，deadline miss=0；actual CCR late=0，
min actual margin=15.788235us。CUR_CONFIRM 49enter/49clear/0fault。
UART ADC TIMING中LATE为原假设tail的统计，不能当作actual CCR late。
full Flash/RAM及UART原始收据已保存，停止时SD/MOE/CCER关闭，CPU halted。

## 关闭12 V后恢复

用户确认12 V关闭后，只通过原bootloader恢复原B启动选择：
`tmp/motor-ident-rs50-restore-1792498009113579300.json` PASS。
没有再使能桥或注入电流，未清故障重试，也未做下一阶段。
