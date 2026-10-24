# 五个启动时刻：0.25倍Ka单次空载板测

用户确认12 V关闭、空载固定/解锁、防护/接线/限流0.5 A及现场断电条件后，
只写非活动A。两次完整回读通过，原B959/boot/private/metadata未变，暂存不激活。
随后用户确认实际上电无报警，执行一次原START，无重试。

## 镜像、方案与回执

- StartupTimestampsDiagnostic，BIN221716 B，
  SHA256 `c2fb66e8710f6ff92295cfe8201ce050173c1d96e9a7a598f0260ed393319108`。
- 0.25 Ka=0.000046875 A/(rpm/s)，BEMF OFF，FRIC ON/0.105 A。
- 240 rpm、Iq±0.50 A、原独立300 rpm超速/其他保护，20000°行程、8 s rundown/12 s lease不变。
- 阶段：`tmp/startup-times-stage-1792648947201373500.json` PASS。
- 运行：`tmp/startup-times-run-1792649090621588900.json` PASS，启动一次、8000点聚合。
- 空载自然RUNDOWN_TIMEOUT，CONTACT=0/FLT=0，不是带工件拧紧OK。

## 实测五个时刻

|字段|1 MHz绝对时标us|相对t0 ms|语义|
|---|---|---|---|
|t0|8295321|0|第一次实际S-curve更新前|
|t_Iq|8358260|62.939|最终IqRef首次abs≥10 mA；当时命令+0.116130 A|
|t_motion|8368854|73.533|连续编码器位移窗口确认；方向+1|
|t_speed|8366259|70.938|abs控制速度首次≥2 rpm；当时+2.784104 rpm|
|t_stable|8635336|340.015|原方向速度条件连续50 ms的确认事件|

连续位移窗口起点8358854 us，即t0+63.533 ms；
10 ms窗口内正向29 counts、反向1 count、9次同方向增量，满足现有诊断16净counts/4增量标准。
这是编码器证据，不是用外部传感器直接测得机械起动的时刻，1 kHz观察也不能宣称1 us物理精度。

UART `MOTOR TEST FF STARTUP`返回VALID=31，上表时标与完整RAM一致；
压缩STT四包同seq422、valid31的五个时标/窗口起点/方向/带符号Iq和speed均匹配RAM。
更早日志seq22仅t0，seq122已记录Iq/运动/测速、尚未stable，未把缺失字段0当实测时间。
无UART丢字节，解码错误0；最终Flash/RAM与精确ELF/BIN哈希均校验通过。

## 能解释什么

并非到290或340 ms电机才第一次动：约63 ms已建立明显Iq命令，约74 ms已有连续位移证据。
约71 ms测速虽已过阈值，但首100 ms审计帧的speed_meas又降到1.06794 rpm，
说明早期过阈值没有持续保持；原连续50 ms判据后来才满足。

旧START_MS=290是成功50 ms连续段的**回溯起点**；
t_stable=340.015 ms是其**确认事件**，两者相差约50 ms是定义差异，不是新增加的控制延迟。
t_motion比t_speed晚约2.595 ms也合理：位移需要连续窗口，速度过阈值只需第一次跨越。

63 ms附近才出现明显Iq命令与当前S-curve/摩擦deadband口径相符：
初段jerk约1000 rpm/s²，从0升至2 rpm理论约63.25 ms；
摩擦补偿在abs(speed_ref)>2 rpm才加入0.105 A。
这是代码与本次时间的相符线索，不单凭这一帧宣称已经证明所有起转波动根因。
本轮不改变PI、trajectory、摩擦补偿、阈值或接入顺序。

## 其他结果

- 加速MAE11.576 rpm，匀速MAE3.737 rpm，超调6.063 rpm，Iq命令峰值0.365 A。
- 总Iq饱和0 ms；AW limited/unexpected=0，FF符号/公式/同步/零加速检查错误均0。
- FOC wall max32.61765 us，deadline miss=0，actual CCR late=0，最小actual margin15.11765 us。
- CUR_CONFIRM109 enter/109 clear/0 fault，encoder timeout/DMA/schedule/stale均0。
- MotorControlTask预检栈余量2512 B，原≥256 B门保持。

## 停止与回退

运行后SD/MOE/CCER关闭、MCU停住，用户确认12 V关闭后仅恢复原B启动选择。
恢复回执`tmp/startup-times-restore-1792649182262901700.json` PASS：
原B/boot/private未变、停在B入口、B应用未运行、motor_commands=0，不再测试。
