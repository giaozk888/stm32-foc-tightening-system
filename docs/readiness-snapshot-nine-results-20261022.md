# 准入快照修复 A：剩余九轮实测结果

## 范围及来源

用户要求一次性完成验证，分别明确确认断电刷A条件、上电无报警且可全程在场立即断电。新修复A补测600/700/800rpm各3次，共9轮，未重跑上轮已经完成的500rpm三轮，**不将新旧两版混称为同版本12轮**。

新候选 `MechanicalReadinessSnapshotCandidate`，BIN SHA256 `abffd548ede6d1b9b635d4ce170554b728cb44f6ba9425f4db43124b00ca5706`，ELF SHA256 `38e59b25fc650d602e1091c7dab7298feff8b8f8e9c8d6f34d3729c590a89299`。

- 断电暂存：`tmp/mechanical-ident-stage-1792675766204211500.json`。
- 实测批次：`tmp/mechanical-ident-batch-1792675998078677600.json`，PASS/acquisition_complete=true，9/9保存完整Flash/RAM/来源哈希/关断证据。
- 控制配置：Ka=0.000046875 A/(rpm/s)，BEMF ψ=0.00034866Wb，friction=0.105A，Iq限幅±0.50A，电压1.60V，超速1000rpm，行程30000°，驱动5s、减速task闭合10.5s、独立lease12s。
- 原100µs ADC样本准入、2ms outer、2.5ms encoder completion、1500µs sample age、200µs transaction/schedule及硬过流保护全部保持，未放宽PI、保护、IRQ或PWM pipeline。
- 每轮只有一个RUN请求，没有自动重试、自动升流、参数写回或DOB执行。最后一轮同样自然结束并关闭输出、CPU停住。

## 三次独立稳态结果

固定窗口在各档原S-curve加速结束后再留0.45s：600为3.65~4.95s，700为4.15~4.95s，800为4.65~4.95s。仅取完整无flag的64ms同步bin，按dt加权；下表各档均值为三轮均值，不是峰值。

| 目标rpm | 第一次rpm / Iq A | 第二次rpm / Iq A | 第三次rpm / Iq A | 三轮平均rpm | 平均Iq A |
|---|---|---|---|---:|---:|
|600|599.3266 / 0.218825|599.2461 / 0.219410|598.5107 / 0.221250|599.0278|0.219828|
|700|699.1100 / 0.229684|698.0244 / 0.232445|699.8826 / 0.230996|699.0057|0.231042|
|800|799.8263 / 0.246050|799.3038 / 0.240254|797.5725 / 0.243804|798.9009|0.243369|

每轮分别有19/11/3个完整稳态bin；800rpm驱动窗口的稳态部分只有约0.192s实际完整bin，不能据此声称做过长时间800rpm稳态耐久。三轮速度均值的样本标准差为0.4496/0.9335/1.1797rpm；平均绝对Id为0.040072/0.041546/0.050000A。

## 启动准入与保护验证

- 9个请求均成功排队并执行。UART先核验 FIX=1，RAM `cl_ready_attempts=1`（每轮重新上电/复位会话），拒绝锁存valid=0，无NOT_READY、无重试。
- 最后一次真实准入检查ADC age按运行顺序为35、37、28、43、29、34、39、28、31µs；clock_valid=1且failed=0，均满足未改变的100µs门限。
- 该字段为该boot最后一次准入检查（可能为实际admit的再复核），不是声称捕获了所有调用的完整时间序列。
- 九轮first_fault.valid全部0；encoder transaction timeout、DMA error、schedule miss、control stale全部0。
- FOC最大wall time=33.688235µs，deadline miss合计0、CCR late合计0，最小实际CCR余量13.388235µs。
- CUR_CONFIRM enter/clear/fault各轮为142/142/0、115/115/0、112/112/0、138/138/0、128/128/0、133/133/0、155/155/0、146/146/0、149/149/0。
- outer trace最大task entry间隔1100µs、最大core wall time195µs、最大观察统计144µs；均包含IRQ抢占及预检，不把不同轮最大值相加冒充单轮耗时。
- 末轮最后STATUS的CTRL=-3.1rpm/DET=-8.9rpm是原闭合/STOP后的稀疏采样，不能宣称整段减速完全无反向波动；未因此改停止或速度保护。本轮最终SWD已证实输出关闭、CPU停住，不再启动。

九次未复现准入误拒绝，支持修复可用，但不是证明今后所有NOT_READY均已消除。其他真实门禁仍可拒绝启动，且保留首个失败项锁存。

## 正向机械参数候选（离线，不自动接入）

仅使用本次同版本九个独立完整捕获，原 `tools/mechanical_positive_fit.py` 与固定窗口准入，不按残差挑样本、不移动时间轴、不改符号：

`Iq_lp20 = (J/Kt)*actual_alpha + (B/Kt)*omega + (Tc/Kt + current_bias)`

| 项目 |64ms主窗口|128ms复核窗口|
|---|---:|---:|
|有效拟合窗口|975|450|
|J/Kt [A·s²/rad]|0.0003860492189|0.0003810736385|
|B/Kt [A·s/rad]|0.001551576508|0.001580642255|
|正向摩擦+电流偏置 [A]|0.1207347546|0.1193566203|
|R²|0.9238994660|0.9546087431|
|电流残差RMS [A]|0.0095445805|0.0071616278|

J/Kt随窗口加倍变化-1.288846%，本批正向归一化模型通过现有离线准则；九个leave-one-session-out全部通过，最大held-out残差RMS0.0125761A。相比旧低速混合批次84%敏感度，本批稳定性明显更好；测试速度、激励范围与版本不同，不将改善单独归因于某一修复。

限制：全是正向数据，库仑摩擦和电流偏置不能分离；Kt没有独立标定，因此不能凭这些数据唯一给出绝对J、B、Kt。原四项正负全模型会因direction与常数项共线而秩亏，不把它当作采集保护失败，也不伪造反向数据。`normalized_positive_qualified=true`只针对上述正向三项归一化模型；absolute_parameters=null，parameter_writes=false，dob_control_enabled=false。

旧UART `LEGACY_FCAL_PASS=0` 是沿用FRIC OFF plateau估计器的字段，该旧准入包含 `!speed_friction_enabled`，而本次按固定配置FRIC=1；因此不使用它冒充本次机械拟合资格。本次机械capture独立使用原同步电流/编码器准入及同会话保护/关断来源验证。

## 各轮原始收据

1. `tmp/mechanical-ident-run-1792675998149077400.json`，600rpm。
2. `tmp/mechanical-ident-run-1792676041494783500.json`，600rpm。
3. `tmp/mechanical-ident-run-1792676071215108900.json`，600rpm。
4. `tmp/mechanical-ident-run-1792676100925859300.json`，700rpm。
5. `tmp/mechanical-ident-run-1792676131093908800.json`，700rpm。
6. `tmp/mechanical-ident-run-1792676161439659200.json`，700rpm。
7. `tmp/mechanical-ident-run-1792676191783658000.json`，800rpm。
8. `tmp/mechanical-ident-run-1792676222609556000.json`，800rpm。
9. `tmp/mechanical-ident-run-1792676253298915200.json`，800rpm。

## 停机与恢复

九轮完成后，用户明确回复“关了”。随后仅恢复原B启动选择：`tmp/mechanical-ident-restore-1792679166747314300.json` PASS。

恢复后metadata generation=1035，active=B、pending=none；原B仍为227964B、CRC627317606。all_app_private_unchanged=true，原B/boot/config/private核验未变。最终VTOR=0x08040000，SD=0、BDTR=0、CCER=0、DHCSR=196611，final_outputs_off=true、final_cpu_halted=true；B application not run=true、motor_commands=0。不再启动或注入电流，辨识参数未自动写入控制器。
