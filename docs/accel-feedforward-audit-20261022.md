# 加速度电流前馈审查：先区分实际切换的功能

本轮严格离线：代码审查、已有记录解码、数值验证、诊断构建。
没有连接串口/调试器、刷写、复位、START或修改B启动选择；保持上轮停止状态。

## 首要发现：给出的六轮不是Acceleration FF OFF/ON

来源：`tmp/bemf-repeat-batch-1792643207376578900.json` 及其6份独立子回执。
280.33→372 ms、加速MAE10.453→12.881 rpm等指标切换的是 **BEMF电压前馈**。

| 轮次 | BEMF runtime | Accel FF runtime | Ka A/(rpm/s) | FRIC | Iq饱和ms |
|---|---|---|---|---|---:|
| 1 | OFF | ON | 0.0001875 | ON 0.105 A | 0 |
| 2 | ON | ON | 0.0001875 | ON 0.105 A | 0 |
| 3 | OFF | ON | 0.0001875 | ON 0.105 A | 0 |
| 4 | ON | ON | 0.0001875 | ON 0.105 A | 0 |
| 5 | OFF | ON | 0.0001875 | ON 0.105 A | 0 |
| 6 | ON | ON | 0.0001875 | ON 0.105 A | 0 |

`tools/accel_ff_audit_report.py --history-batch ...` 根据同次回执/读回识别实际开关，
不会将BEMF ON误标成Acceleration ON。该批全部Accel ON、Ka相同，
不能把组间差异归因于“打开Acceleration FF”。
既有480个同seq FRC R/C日志对，观察到max accel=200 rpm/s、max Accel FF=0.0375 A；
日志有丢失，明确不冒称全速率极值。轨迹/计算代码本身也有同样理论上界。

## 单位、符号、实际控制链

- `speed_ref_rpm`是机械rpm。
- `speed_scurve.acceleration_rpm_s`是机械rpm/s，不是rad/s²、电角加速度或rps/s。
- jerk=1000 rpm/s²，accel最大200 rpm/s；本轮没有改这些参数。
- Ka=0.0001875 A/(rpm/s)，直接乘原机械加速度，不乘2π/60或pole_pairs。
  若改用机械rad/s²，等效系数才应乘60/(2π)；代码并没有做此单位切换。
- 最大Accel FF=200*Ka=0.0375 A，占现有0.50 A Iq限幅7.5%。
  这说明没有明显倍数单位错误，不代表已根据转动惯量/转矩常数辨识出最优Ka。
- ENCODER_DIRECTION=-1：AS5047 raw下降代表应用正向角度/正rpm；电角速度取同一有符号方向，pole_pairs=10。
- Park：Id=Iα*cos+Iβ*sin，Iq=-Iα*sin+Iβ*cos；逆Park为对应逆变换。
- 正speed_ref误差→正P项→正IqRef；正机械accel_ref配正Ka也产生正Iq。
  既有240 rpm的正方向转动及六轮WRONG_MS=0支持应用坐标一致，未发现Accel FF反号矛盾。
  这不是新的独立轴端转矩测量，不能仅靠软件证明所有物理相线绝对正确；本轮不改相序/零点/方向。

正常SPEED路径的实际顺序：

```
原S-curve Step(speed_target, 同一次dt_meas)
→ 新speed_ref及同一speed_scurve.acceleration_rpm_s
→ speed_error、P项、原积分候选、既有bleed/SB2 shaping
→ SpeedFriction_Apply:
   iq_acc_ff = enabled ? Ka*accel_ref : 0
   iq_fric = FRIC enabled && |speed_ref|>2rpm ? sign(speed_ref)*0.105 : 0
   tentative_total = (P + candidate_I) + iq_acc_ff + iq_fric
   AW按tentative_total与统一±iq_limit决定积分准入
   iq_pi = P + admitted_I
   iq_raw = (iq_pi + iq_acc_ff) + iq_fric
   iq_cmd = clamp(iq_raw, -0.50, +0.50)
→ 一次发布foc_iq_ref_A
→ 正常dq电流PI/SVPWM/一拍PWM pipeline
```

AW不是只看iq_pi；上下边界同时减去acc_ff/friction以给PI保留真实余量，
反向解饱和允许，原mandatory bleed/unload不被AW否决。
原SB2的积分增长/卸载shaping保留，不称其为新加的AW错误。
该批speed Iq saturation=0，不能用“新FF更早撞Iq限幅”解释这组均值差。

## 同步/旧值排查结论

`FOC_EncoderSpeedUpdate`中SPEED只执行一次Scurve Step，然后在同一调用中读取speed_ref和accel_ref做FF。
dt_meas来自原编码器接受帧；不是MonitorTask在另一周期生成加速度。
模式改变时原SpeedScurve_Reset同时清参考与加速度；进入SPEED的既有重置保持不变。
匀速最终相位将acceleration明确写0，乘法FF也严格回0。
没有发现额外提前/延迟一拍、重复轨迹更新或跨模式使用旧accel的问题。
已有测速20 ms LPF、已有50 us PWM pipeline不是本轮新引入的错位，没有改它们。

## 独立诊断，仅candidate A且默认关闭

新增 `FOC_ACCEL_FF_AUDIT` 默认OFF，四个独立gain preset继承当前正常候选。
没有改速度/电流PI、Scurve、摩擦、BEMF算法、DQ、保护、IRQ或A/B boot。
所有测试构建BEMF默认OFF；未来实际测试还必须读回OFF，避免再次混淆。
ψf旧配置保留但OFF时不产生电压补偿，不自动写任何正式参数。

新增代码：

- `firmware_common/speed_accel_audit.h/.c`：单任务只读观察器、有限二进制窗口及逐速度周期统计。
- `firmware_common/speed_accel_audit_log.cc`：只在MonitorTask输出4个同seq压缩token。
- `firmware_common/speed_accel_feedforward_binding.inc`：仅诊断构建的重置和Monitor取帧。
- `foc2_app_a/Core/Src/main.c`：仅宏内的轨迹计数及控制输出发布后的观察；无控制反馈写回。
- `firmware_common/speed_friction_compensation_binding.inc`：诊断时避免重复FRC日志，正常构建不变。
- A CMake/presets、`tools/accel_ff_audit_report.py`、`tests/test_speed_accel_audit.py`及host/codec fixtures。

记录字段：timestamp、speed_ref/meas/error、accel_ref、iq_pi、iq_acc_ff、iq_fric、
iq_raw、iq_cmd、speed_integrator、IQ sat/AW/release/enable flags、dt、trajectory update counter/phase。
二进制帧64 B，16帧、100 ms间隔，保留进入SPEED后约0~1.5秒，覆盖起转附近及最初500 ms；
这不是START前500 ms预触发或1 kHz连续历史。受RAM限制，未伪称更高时间分辨率。
另在每个既有速度更新累计最大加速度/FF/占比、sat时间/首发时间、异常符号、零accel残留、
公式错误、轨迹消费周期不符、PI/FF异向、AW准入异常等，不进入20 kHz ADC ISR。

PI与FF异向只记现象：超速制动时PI抵消惯性FF可能合理，不能看到乘积<0就自动宣判反号。
AW异常检查使用**积分候选对应的总输出**，不依赖已含AW标志的最终sat标志自证正确。
MonitorTask按同seq输出AAC R/T/C/I；测试实际最大32-bit字段编码仍不超过32 B，不在ISR printf/UART。
重置只清84 B元信息、用count/generation废弃旧帧，不在reset分配或清零1 KB临时栈数组。
该诊断仍有任务执行开销，未来板测必须重验任务栈和FOC/CCR时序，不用离线构建替代实测。

主机报告只读取保存Flash/RAM/ELF并核验身份；自动检查公式、总和、最终限幅、零accel、
trajectory/消费seq同步，提供前500 ms PI/误差与积分器/saturation对照。
拒绝BEMF非OFF、非Ka编译定义不一致、空窗口或基线FF非0的假对照。
运行时同负载/配方/FRIC和有效覆盖度仍需人工/既有脚本核验，不能仅靠build key保证物理一致。

## 编译及离线结果

| A预设 | Ka A/(rpm/s) | 最大FF A / Iq比例 | Flash B | RAM B | 构建 |
|---|---:|---:|---:|---:|---|
| AccelFfAuditGain0 | 0 | 0 / 0% | 220156 | 130680 | PASS |
| AccelFfAuditGain025 | 0.000046875 | 0.009375 / 1.875% | 220164 | 130680 | PASS |
| AccelFfAuditGain050 | 0.00009375 | 0.018750 / 3.75% | 220172 | 130680 | PASS |
| AccelFfAuditGain100 | 0.0001875 | 0.037500 / 7.5% | 220172 | 130680 | PASS |

Gain0用Ka=0且FF框架仍ON，数学路径等价Accel OFF，FRIC仍ON；不要把FF STATUS ON=1误认为实际有加速补偿。
没有发现符号疑点，所以未新增-0.5Ka反号实验；不为得到更好结果任意反转物理转矩方向。

RAM上限131008 B，诊断静态余量仅328 B，不是可随意增加缓冲区的富余内存。
各构建13条既有unused/RWX警告，与默认构建逐条同类，无新增警告/错误。
7项新审查/真实C/codec测试及37项既有AF/FRIC/AW/Scurve/BEMF回归通过，共44项相关测试。
现有当前PI、AW、FRIC和Scurve控制数学没有为了测试而重写：
主路径去除仅诊断观察语句后逐函数相等；Scurve/AF/FRIC对象也逐字节相同。
正式默认A重编仍SHA `6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f`，
B保留文件SHA不变，未操作板端B951。

日志：`tmp/accel-audit-final-tests.log`、`tmp/accel-audit-regression.log`及4个`*-final-build.log`。

## 根因排序（不把推测写成已证明）

1. **已确认的归因混淆**：已有六轮切BEMF，不是切Acceleration FF；后者两组均ON。
2. **对已观察BEMF差异优先怀疑模型/标定偏置**：ψ来自命令电压、未资格化Rs/Ld，拟合截距约90 mV。
   不是测得的端电压/开路磁链；不能假设该ψ能直接给出准确电压前馈。这是线索，不是定案。
3. **待隔离的闭环动态/工作点交互**：PI、既有积分shaping/测速滤波与补偿共同作用，
   “Iq峰值更大”可能是误差增大后的反馈结果，不能据此认定加速FF符号反了。
4. 目前没有单位、同步或总输出AW代码错误的直接证据；Ka也未根据机械J/Kt独立标定，
   7.5%只是幅值上界，不代表最佳值。不能用本批证明Accel FF好或坏。

## 下一轮人工顺序（本轮不执行）

先固定BEMF OFF并读回，FRIC=0.105 A/Accel框架、240 rpm、限幅、配方等保持一致。
先Gain0基线，再按0→0.25→0→0.5→0→1.0做配对；每轮需人工安全条件/校准/时序及任务栈通过，
真实保护或关断证据异常即停止，不自动重试/扫增益、不强制CONTACT。
检查AAC同seq字段与完整8000点聚合，不能将缺日志、未settle或无减速段填0。
选出有信息量的一对后才由人工决定是否各3次复测；不基于单轮自动选新Ka。
若Gain0与FF OFF核验一致且0.25已恶化，先分析同周期记录，不自动向上跑更大增益。
