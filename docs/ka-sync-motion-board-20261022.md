# 240 rpm 同步短窗上板记录

## 范围与身份

用户确认12 V开启、无报警、限流0.5 A、转轴解锁、空载固定/有防护、现场可立即断电后，执行一次原START状态机。
同一诊断A完整核验，无需重刷；不改Ka、控制参数、保护或IRQ。
Ka=0，摩擦补偿0.105 A，BEMF关闭，240 rpm，Iq限幅±0.50 A，原8秒rundown/12秒板端限时保留。

- 准备记录：`tmp/ka-sync-motion-stage-1792656029134379500.json`
- 采集记录：`tmp/ka-sync-motion-run-1792656084682985400.json`
- BIN SHA256：`5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136`
- ELF SHA256：`f00c940b6f868f4c1f4c88c028db23742dd7c33412ddac3a516256da17b68ed3`

同一轮完整Flash/RAM/BIN/ELF身份校验通过。仅一次START，无自动重试或参数写入。
自然结束为RUNDOWN_TIMEOUT、CONTACT=0、FLT=0；这是空载观察完成，不是真实拧紧OK。

## 全程运行指标

|指标|实测|
|---|---:|
|FOC wall max|32.94118 µs|
|deadline miss / CCR late|0 / 0|
|actual CCR margin min|15.13529 µs|
|加速段速度MAE|12.037 rpm|
|匀速段速度MAE|3.618 rpm|
|超调|6.113 rpm|
|Iq命令峰值|0.373 A|
|任务观测Iq瞬时峰值|1.103 A|
|Iq命令饱和时间|0 ms|
|UART丢字节|0|

Iq瞬时峰值不等于持续电流；没有用平均值掩盖该观测。此轮不比较新旧Ka，未据此改电流限幅。

## 600 ms附近64点同步窗口

首点encoder相对诊断begin时间600022 µs，首末点跨度62937 µs。
64点全部质量标志为0，read_failures=0，时间戳/ADC序号末端重构一致。

|指标|实测|
|---|---:|
|encoder间隔|945～1055 µs，平均999.03125 µs|
|电流source时间减encoder时间|69～170 µs，平均118.359375 µs|
|任务读取时电流年龄|25～75 µs，平均30.5625 µs|
|快照发布片段max|81 cycles / 0.47647 µs @170 MHz|
|相同20 ms LPF重放最大误差|0.05225 mA|
|可在encoder时刻双边插值的电流点|63/64（首点不外推）|
|原始机械增量方向|64正向 / 0反向|
|累积机械位移（含首点相对前一采样增量）|+38.342285°|
|filtered speed|84.13～106.83 rpm，均值96.256406 rpm|
|瞬时机械速度|65.91797～128.30213 rpm|
|Iq任务快照|−0.1448～+0.4376 A，均值+0.151633 A|
|LPF(Iq−摩擦补偿)|+0.0056～+0.0520 A|
|filtered加速度|−1570～+1620 rpm/s；40正 / 23负；首点无前值|

### 能确认与不能确认

电流source是ADC pair已有的软件读取/接受时间，encoder是SPI接收时间；不是测量到的模拟采样孔径/物理转子绝对同步。
观测电流来自约1 kHz任务快照，不是保存了全部20 kHz ADC。
本轮直接测得软件来源偏移约0.118 ms，没有证据把它说成数十ms的来源错位。
同参数LPF重放通过，说明诊断滤波实现/记录可复现；不等于机械模型已验证。

窗口内机械持续正向，Iq均值为正，但瞬时Iq有负值、速度增量仍正负波动。
因此不能把单点负Iq或负加速度解释为“Iq和机械正方向相反”。
64点仅约63 ms，不覆盖完整起转/加速过程，且无独立负Iq反向测试。
此窗足以检查来源时间/滤波形状，不足以可靠辨识惯量Ka或选择最优增益。
保持`ka_identified=null`，不自动翻符号、不用挑点/最优延迟让回归变正。

## 收尾

采集后STOP/SAFE，确认SD/MOE/CCER关闭、MCU停住。
用户确认12 V关闭后，仅恢复原B启动选择：
`tmp/ka-sync-motion-restore-1792656303784481500.json` PASS。
元数据generation983、B已确认、无pending；B/boot/private应用数据未变。
VTOR=0x08040000，DHCSR=0x30003，SD=0，BDTR=0，CCER=0。
停在B入口，B应用未运行，恢复步骤motor_commands=0，不再运行电机。

运动包装器`tools/ka_sync_motion_board.py`复用原受保护START所有者。
拒绝保护异常；只接受精确的正常空载RUNDOWN_TIMEOUT作为观察终点；
不把短窗质量失败重标为有效，不自动重试，默认仅文件检查。

本轮再次运行`python -m unittest discover -s tests -p test_ka_sync*.py`：11项通过。
输出中的Fresh OFF/confirmation错误为测试主动验证缺失确认时拒绝硬件操作的预期结果。
