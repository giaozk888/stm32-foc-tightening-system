# ψf/Ke 300/400 rpm补测

人工明确允许提高超速阈值至500 rpm，并确认电机/传动允许400 rpm、
转轴解锁、脱开负载、空载固定有防护、现场可立即断电。
刷写前12 V关闭、MCU供电，电源限流0.5 A、现有接线不变。

## 构建及执行范围

- A专用预设 `PsiKeHighSpeedDiagnostic`，继承500 rpm trip诊断，
  新增默认关闭 `FOC_PSI_IDENT_API400`，只将速度API范围从250扩到400 rpm。
- 原300 rpm PSI预设及单改阈值的500 rpm预设不变；正式B不变。
- `tools/psi_ke_high_speed_board.py` 固定只采300和400，各一次，禁止自动重试。
- 原PSI runner仅参数化计划/读回上限，默认仍100/200、API250/trip300。
- 质量失败记录后继续下一点；独立保护、身份/关断/时序证据异常立即停止整批。
- 保留±0.50 A限幅、1.60 V矢量限幅、原PI/FF/摩擦、采样/编码器/时序保护和12秒lease。
- 每点稳态门限500 ms、固定窗口2秒、最多5秒驱动、原S-curve停止，最晚7秒关断。
- 无自动BEMF应用、相序/电角度/PI修改。

构建Flash215860 B、静态RAM129408 B，13条既有警告，无新增类别/错误。
23项相关离线测试通过：`tmp/psi-high-tests.log`。
BIN SHA256：`ae86125e772e65599fcdbf424bd449f38f649c6aff472f5c17a1c136b1a8e53d`。
ELF SHA256：`b1773b0eba83a04c49e20f61ae5f0723afa11f896a11c221ee1a9cc4056b6bc4`。
预处理逐函数核验除两处API常量替换外控制/保护/PWM/角度函数不变。

先按原低速镜像身份验证B936完整恢复收据，再切换新A校验器，
不把旧收据篡改为新镜像、不跳过全Flash比较。
基线：`tmp/psi-ke-restore-1792588592105201500.json`。

## 暂存

`tmp/psi-ke-stage-1792590139635134300.json` PASS。
仅非活动A，独立两次完整回读；B/boot/private/metadata未变，
activation=false，motor_commands=0，输出关闭、MCU停住。
等待人工上电/无报警确认后，才执行一次300/400批次。

## 实机采集结果

人工确认“开了。无”后执行一次批次，无自动重试、无额外速度点。
`tmp/psi-ke-run-1792590299773811900.json` complete/PASS，表示采集完成，
不是物理参数测量已资格化。两点分别校准/预检，原bootloader正常试运行/自动确认。

| 项目 | 300 rpm | 400 rpm |
|---|---:|---:|
| 实测窗口平均rpm | 299.37152 | 399.55621 |
| 窗口有效/拒绝/总观察 | 42/0/42 | 40/1/41 |
| mean Id A | +0.00276670 | -0.00996089 |
| mean Iq A | +0.15926658 | +0.21134813 |
| mean Vq命令 V | +0.44054946 | +0.54278934 |
| mean Vd命令 V | -0.02904664 | -0.03465049 |
| mean bemf估计 V | +0.31630445 | +0.37802145 |
| mean omega_e electrical rad/s | 313.50122 | 418.41434 |
| 单点mean ψf Wb | 0.0010087829 | 0.0009035366 |
| ψf样本SD Wb | 0.0001346502 | 0.0001961212 |
| FOC wall max us | 32.70588 | 32.38824 |
| deadline miss / CCR late | 0 / 0 | 0 / 0 |
| actual CCR min margin us | 14.70000 | 13.69412 |
| actual CCR commits | 246505 | 266706 |
| CUR_CONFIRM enter/clear/fault | 115/115/0 | 131/131/0 |
| ADC零点valid/reject | 4000/40 | 4000/44 |
| ADC零点 U/V | 1559/1563 | 1559/1563 |

400 rpm的一帧仅未通过辨识准入，未进入均值，不属于保护故障。
两点第一故障快照valid=0，cl/adc/foc fault=0；encoder valid=1，
编码器timeout/DMA/schedule/control stale计数全0。
R/I/E/S窗口日志分别42/42和41/41完整，按相同index连接。
每点Flash和RAM文件SHA独立复核通过；B/boot/private未变；
最终SD=0、MOE/AOE关闭、CCER=0、CPU halted。
BDTR寄存器并非整个为0，但MOE/AOE位确实为0，不把其他计时位误报为功率使能。

### 拟合，明确区分批次与假设

本次300/400两点带截距线性拟合：

```
bemf = 0.00058826776 * omega_e + 0.13188179 V
psi_f = 0.00058826776 Wb
Ke_phase_peak/mech_rad_s = 0.0058826776 V/(mechanical rad/s)
```

只有两点，残差自由度0。R²=1是代数必然，不是独立准确度证明。
单点mean ψf由bemf/omega计算，与带非零截距的拟合斜率本来就可能不同。

另将上一批合格200 rpm点作为**跨批次参考**合并为200/300/400三点，
Rs=0.78 Ω、Ld=20.03 µH、pole_pairs=10完全相同，没有重算或更换参数：

```
psi_f = 0.00069731983 Wb
offset = 0.09008983 V
Ke_phase_peak/mech_rad_s = 0.0069731983 V/(mechanical rad/s)
R² = 0.99210870
residual RMS = 0.00537691 V
residual DOF = 1
```

原200点来自 `tmp/psi-ke-run-1792588363118117500-200.json`，不是本批新测。
跨批次初始角度、温度、零点并非完全一致，且原200点ψf离散较大；
因此三点结果是更有信息量的**命令电压模型候选**，不是可追溯物理磁链标定。
约90 mV拟合截距提示不可忽略电压/模型偏置，不能直接归因为某一个器件或Rs。
Vq仍是PWM命令、Rs/Ld仍是用户指定未资格化假设；不得以较高R²掩盖这些系统误差。
没有自动接入BEMF feedforward、改PI或写KVS/正式B。

### 收尾

用户确认“关了”后，仅恢复原B启动选择；恢复收据：
`tmp/psi-ke-restore-1792590404078518900.json` complete/PASS。
最终输出关闭、CPU停在B入口、B应用未运行，motor_commands=0。
本批结束，不追加测试。
