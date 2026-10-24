# 五个独立启动时刻的记录口径

依据用户给出的t0/t_Iq/t_motion/t_speed/t_stable表，新增候选A诊断记录，
不把命令建立、运动证据和测速滤波延迟混为一个指标。不刷板、不启动电机。

## 字段

|字段|记录点|含义/限定|
|---|---|---|
|t0_us|非零速度指令第一次真正执行SpeedScurve_Step之前|轨迹开始，不是UART接收/START ACK时间|
|t_iq_us|最终foc_iq_ref_A已发布后，首次abs(IqRef)≥10 mA|电流命令明显离零；不代表实际转矩已被测得，保留带符号iq_at_event_a|
|t_motion_us|首次满足连续编码器位移证据的采样时标|运动确认时刻，不冒充独立机械测量；另存motion_begin_us为该连续窗口起点|
|t_speed_us|控制速度abs(speed_meas)首次≥2 rpm|第一次测速过阈值，无50 ms持续要求；另存带符号速度|
|t_stable_us|既有SpeedFriction_Observe的moving首次0→1之后|当前≥2 rpm连续50 ms的确认事件，不重新实现/修改该判据|

重要纠正：原START_MS在满足50 ms后**回溯到该连续段起点**，不是确认事件t_stable。
保留旧START_MS原含义，新增字段不重命名、不覆盖旧统计；新旧值不能直接混用。

输出五个绝对微秒时标和相对t0延迟，valid bit区分“未发生”和“时间恰好为0”。
32位1 MHz计时回绕按无符号差值处理；时间粒度来自同一计时器，
但控制/编码器消费约1 kHz，不能宣称真实运动时刻精确到1 us。
编码器sample_us是现有SPI事务采样时标，不是示波器测得的转子运动起始时刻。
old日志100 ms间隔不足以精确还原这些事件，本次不补造过去五轮的值。

## 连续位移证据（仅诊断阈值，不是新保护）

用原先通过合理性检查的14位encoder delta和既有ENCODER_DIRECTION，
不改角度/速度估计，诊断独立累加，不依赖会被状态机重置的position变量。

- 同一运动方向净位移至少16 counts（16/16384圈≈0.3516°）；
- 至少4次沿该方向增量观测，连续窗口跨度至少10 ms、最多50 ms；
- 沿该方向增量间隙≤5 ms，累计反向量≤2 counts；超出只重启诊断窗口，不干预控制；
- 前命令采样、重复/倒序采样、单跳点、往返噪声、先动一下后静止不能触发确认。

运动方向独立记录motion_direction：即使反向起转也要记录真实位移，
不能因为不符合命令方向就假称“没动”。原稳定运动条件仍按原指令方向，不改动。

宏：STARTUP_IQ_THRESHOLD_A、STARTUP_MOTION_MIN_COUNTS、
STARTUP_MOTION_MIN_FORWARD_SAMPLES、STARTUP_MOTION_CONFIRM_US、STARTUP_MOTION_WINDOW_US、
STARTUP_MOTION_MAX_FORWARD_GAP_US、STARTUP_MOTION_REVERSE_TOL_COUNTS、STARTUP_SPEED_THRESHOLD_RPM。
它们不改变current discriminator、CUR_CONFIRM、NO_ROTATION、PI或任何安全阈值。

## 构建与采集

编译开关FOC_STARTUP_TIMESTAMPS_DIAG默认OFF，独立StartupTimestampsDiagnostic继承AccelFfAuditGain025。
只在MotorControlTask既有路径被动记录，20 kHz ADC/FOC ISR完全未加代码。
每次统计reset/新速度段清记录，各事件首次锁存，停止后保留供读取。

- RAM结构startup_timestamps，76 B；valid bits：t0=1、Iq=2、motion=4、speed=8、stable=16。
- UART只读：`MOTOR TEST FF STARTUP`，返回VALID和五个绝对时标，不改变状态。
- MonitorTask在事件valid变化时发送四条压缩STT A/B/C/D日志，用同seq关联，不按相邻接收时间拼接。
- `tools/startup_timestamps_report.py --receipt ... --elf ...`离线解码完整RAM，校验Flash/RAM/BIN/ELF哈希。
  旧镜像没有该结构，拒绝把旧统计当成新数据。

本轮只准备离线功能；下一次人工板测需新诊断镜像，不能声称当前板上已记录。
当前板保持原B959启动选择、输出关闭/MCU停住；本轮未访问板端。

## 离线验证结果

StartupTimestampsDiagnostic编译通过：Flash221716 B、RAM130768/131008 B（静态余240 B）。
13条原有unused/RWX告警，无新增warning/error；新增记录不表示新镜像已通过板端时序验收。
5项新测试通过：实际C正反向/五事件独立、单点/噪声/静止/反向/断续、计时回绕/重置、
valid零时间/缺失值、真实PW_LOG压缩codec32 B边界、实际预处理owner去掉观察调用后完全一致。
另31项既有AccelFF/FRIC/审计/五轮与六轮编排回归通过。

原AccelFfAuditGain100及正常BemfFittedFluxCandidate重编后BIN哈希不变；B文件哈希不变。
Scurve、FF、FRIC对象逐字节相同，current/encoder/PWM/guard数学owner逐函数未改。
日志：`tmp/startup-timestamps-final-build.log`、`tmp/startup-timestamps-tests.log`、
`tmp/startup-timestamps-regression.log`。
