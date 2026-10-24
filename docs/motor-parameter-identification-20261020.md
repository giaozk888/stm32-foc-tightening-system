# candidate A：静止转子 Rs / Ld / Lq 辨识诊断

## 本轮交付与边界

独立 preset `MotorParameterIdentificationDiagnostic` 继承当前
`Tightening240rpmFriction105OnCandidate`。默认 `FOC_MOTOR_IDENTIFICATION_DIAG=OFF`；
仅该诊断 preset 开启，不在 B 添加此功能。
本轮没有连接调试器/串口、没有烧录、没有修改板端 B804 选择或启动电机。

新增：

- `firmware_common/motor_identification.h`：波形、单次状态、32 帧二进制记录、额外诊断退出界限。
- `firmware_common/motor_identification_binding.inc`：独占诊断任务、手动命令与原安全准入适配。
- `tools/motor_identification_report.py`：只读 UART 解码、候选 Rs/RL 拟合与 PI 建议，无设备访问。
- `tests/test_motor_identification.py`：实际 C 核心/绑定、门控、合成 RL、解码/质量拒绝、冻结回归。

条件接入：

- `foc2_app_a/Core/Src/main.c`：只有诊断编译才替换 task owner，在原 PI 前设置参考、原输出后记录。
- `firmware_common/latest_original_fsm.inc`：诊断独占准入；仍复用原 ready/session/gate enable。
- `firmware_common/protected_closed_loop.inc`：在原 local-only MOTOR TEST dispatcher 接入 IDENT。
- `foc2_app_a/CMakeLists.txt` / `CMakePresets.json`：A-only 开关、互斥校验与诊断 preset。

current/speed PI 参数、S-curve、Acceleration FF、0.105 A Coulomb 项、Park/SVPWM、
one-cycle pending/commit、CUR_CONFIRM/TWO_SAMPLE、独立硬过流、encoder/timing 保护、
IRQ 优先级以及 A/B boot 机制不变。正常 A 不含新逻辑，重建 BIN 哈希不变。
诊断独占 IQ 模式，绕过速度/位置/摩擦/FF 的参考生成，不更改那些算法；普通 START
被拒绝，不能进入 tightening，也不能被暗中转换成辨识动作。

## 幅值、时长、退出

|阶段|手动单次波形|时间|记录|
|---|---|---|---|
|Rs|IdRef=+0.050 / +0.075 / +0.100 A，IqRef=0|每点最多 400 ms|200 ms 后每 6.25 ms 一帧，32 帧|
|Ld|IdRef +0.050→+0.100 A，IqRef=0|100 ms 预偏置，104 ms 总上限|99.8 ms 开始连续 32 对，50 us/对|
|Lq|IqRef +0.050→+0.100 A，IdRef=0|同 Ld|同 Ld|

每次只接受一个明确 LOCKED CONFIRM 命令，`used` 不清零，不自动换档/重试。
每个新点需保存旧数据后人工复位并重新校准/预检；不提供 fault-clear 重试捷径。
结束调用原 ProtectedLoop_Stop，参考归零、pending 失效、SD/MOE/CCER 关闭。
无正常 ADC 回调时，task 还检查 duration+1 ms，原独立 TIM7/stale/lease 继续生效。

额外诊断拒绝/停机条件（不是放宽原保护）：

- abs(Id) 或 abs(Iq)>0.20 A；生成的 Vdq 向量幅值>0.20 V。
- abs(speed)>2 rpm 或机械角相对起点变化>0.10°。
- 非有限量，accepted pair 不连续或时间不在 45–55 us。
- STOP、原任一保护、session 丢失、准入失败。

0.20 A/0.20 V 是新增诊断退出包络，参考最多 0.10 A；没有增加现有 current/voltage
控制限幅或安全阈值。电压越界记录点在原 PWM stage 之后、下次入口 commit 之前，
立即使用原 STOP 使该 pending 失效，没有通过截断 Vd/Vq 修改 PI 数学。
任务和 binary hooks 只在 opt-in 模式生效；ISR 没有 UART/printf/拟合/动态内存。

**转子静止不是“空载”**：尤其正 Iq 会产生转矩。必须断电安装额定适合的机械锁定
夹具/防护，不用手或手持工具抵轴。LOCKED 是操作者确认，不是软件检测到了夹具；
编码器位移门限只作额外退出，不能代替锁定。 electrical zero / pole pairs / phase mapping
必须先有独立确认；本模式不自动对齐转子、不改零点、不改方向。

## 日志与导出

UART 不在 active 阶段导出逐帧。结束后查询：

```
MOTOR TEST IDENT STATUS
MOTOR TEST IDENT GEOMETRY
MOTOR TEST IDENT ROW 0
...（直到 N-1，最多31）
MOTOR TEST FAULT
MOTOR TEST TIMING
ADC TIMING
```

二进制结构 `motor_ident` 和 ELF 可在门极关闭、CPU 停住后另存 RAM；不提供主动板测脚本。
每帧：mode、相对 timestamp us、sample_index K、ADC seq、stage 前 pending source seq、
IdRef/IqRef、Id/Iq、Vd/Vq、electrical angle、speed、status、reason。
最终 STATUS 单独携带 DONE/ABORT 和最终 reason，不将 ACTIVE 帧 F=0 冒称最终无故障。
Vd/Vq 是软件控制命令，不是独立相电压表读数。
UART DR/QR/D/Q 为 uA，VD/VQ 为 uV，A 为 urad，RPM 为 mrpm；完整浮点值在 RAM。
GEOMETRY 为只读 ARR/CCR4/CR1/RCR/ADC1 JSQR；不修改 UDIS/UG/触发器。

只读解码例：

```
python tools/motor_identification_report.py tmp/ident-rs50-uart.txt --decode-mode RS
```

输出一个 run JSON，多个独立 run 可人工合并为 `{"runs":[...]}`。
独立保存为候选文件（如 `tmp/motor-params-candidate.json`），不进入 recipe/NVM/PI。
每个 run 还需加入同会话原保护/时序收据引用：

```
"protection_evidence": {
  "verified": true, "source": "同镜像本轮已保存原始保护/时序收据路径",
  "fault": 0, "deadline_miss": 0, "ccr_late": 0
}
```

不能因脚本需要这些字段而手填未验证的 PASS；缺少证据就保留 null/失败原因。

## 辨识方法与拒绝伪结果

### Rs

转子静止时，d 轴稳态 `Vd ≈ Rs*Id`，每点给出 `mean(Vd)/mean(Id)` 供检查。
正式候选采用 >=3 个不同小电流点的线性拟合 `Vd=Rs*Id+Vbias`，避免把恒定驱动
偏置全算成 Rs。至少 25 mA measured span，跟踪/交叉轴/噪声/漂移/拟合质量均需通过。
输出 per-phase、Y-equivalent 的有效电阻候选，非线间电阻，也不宣称四线法绕组测量。
低阻电机在 50–100 mA 时电压只有数 mV，死区、MOSFET/线阻、ADC 噪声及 nominal
DC bus 比例误差可能占主导；数据不足不得自动加流或放宽门限。

### Ld / Lq

**不把闭环 current PI 的阶跃 rise time 直接当 tau**。
使用已确认 Rs 和实际记录的控制电压波形，通过静止 RL 方程
`di/dt=(v-Rs*i-Vbias)/L`，在 host 上拟合电机 tau，`L=tau*Rs`。
每个 ADC interval 的电压分成 latch 前/后两段，指数解而非简单差分放大噪声。
先生成的 CCR(k) 在下一 ADC(k+1) 入口提交，不能把 V(k) 与同帧 I(k) 直接配对。

本 estimator 明确要求 **命令到采样有效滞后为两帧** 的时序证明，以及采样 aperture
到目标 bottom 的分数 `f`；它不自动猜 lag、不调整现有 pipeline。
采样/转换/ISR timestamp 不等价，不能直接用 ISR entry 的 CNT 代替物理 aperture。
只有结合本板 ADC JSQR/采样时间/触发方向与 TIM1 preload/RCR/CCR4、原 actual commit
margin 收据，必要时加示波/逻辑分析，证明 bottom 在 interval 的位置后，才填写：

```
"latch_evidence": {
  "verified": true, "source": "实际采样/bottom/commit证据路径",
  "command_lag_cycles": 2,
  "sample_to_bottom_fraction": 0.3,
  "late_count": 0
}
```

**0.3 仅是离线测试样例，不是此板的已测值，不可照抄。** 若实测并非此两帧模型，
应先修订离线对齐模型，不得靠换 lag 选一个最好看的 L。UART decoder 默认 verified=false。
缺少该证据时输出 TIMING_UNQUALIFIED，Ld/Lq=null，绝不返回看似有效电感。
32 对必须连续、pending source=seq-1、无 hold/缺样；至少 15 mA 动态范围。
tau 必须可在 20 kHz/1.55 ms 窗口中分辨：搜索范围从 3*dt 到窗口/2；边界、
拟合噪声高或平坦不可辨识均拒绝。太快/太慢不会强行产出结果，也不自动改频率。
若 PWM ripple/开关非线性导致平均 RL 模型不适用，也应报告 insufficient。
Ld/Lq 的命名依赖 d 轴确实对准磁链；不确定时只能称测试轴有效电感。

### 候选 PI 建议

```
python tools/motor_identification_report.py tmp/ident-captures.json --wc-rad-s 1884.955592
```

wc 输入单位 rad/s；上例只是 2*pi*300 的使用示例，不是自动选择目标带宽。
只有 Rs/Ld/Lq 全部质量通过才给出：

`Kp_d=Ld*wc; Ki_d=Rs*wc; Kp_q=Lq*wc; Ki_q=Rs*wc`。
Ki 单位 V/(A*s)，原实现已乘 Ts；建议值不能再误乘/漏乘离散 Ts。
仍须考虑现有 50 us pipeline/采样延迟、噪声与实际电压余量，不自动修改任何 PI。
**本轮尚无硬件辨识数据，未给出真实电机 Rs/Ld/Lq 数值。**

## 构建与离线证据

|配置|Flash used|RAM used|结果|
|---|---:|---:|---|
|A MotorParameterIdentificationDiagnostic|212732 B/229376|130592 B/131008|通过|
|A 正常 0.105 A ON|217420 B/229376|129152 B/131008|通过，BIN 不变|
|B FrictionBUnchanged|228300 B/229376|128792 B/131008|通过，BIN 不变|

诊断 BIN：`15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d`。
ELF：`1e4cf495f8da3ba7dec4c7c211d23ee2c623b7c852a915dd1aa4216cd8909d9f`。
正常 A BIN：`3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`。
B BIN：`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。

诊断未被内联进 RAM FOC 函数，避免首次尝试时的 RAM 链接溢出；仅把诊断 helper
noinline/-Os 放 Flash，未改 current-loop math 或降低 heap/stack。最终仅剩 416 B
链接 RAM 余量（已有 heap/MSP reserve 保持），必须另做实物 stack/timing 预检。
没有硬件实测，不能宣称新增 hooks 已通过 50 us。
现有 unused/RWX warnings 存在；诊断替换 tightening task 后还有原流程函数变为
unused 的诊断构建 warning，未全局屏蔽 warning，不能报告为零 warning。

新增 6 项测试：C 波形/时长/包络、实际 command binding one-shot/忙拒绝、停机
冻帧 UART 解码、已知 Rs=0.1 ohm/Ld=40uH/Lq=50uH 的合成恢复、坏数据拒绝、
正常控制与 PWM/保护函数冻结/原 A-B 哈希检查。合成值不是实机结果。
既有 0.105 A 3 项、摩擦 8 项、PWM pipeline 9 项、zero admission 12 项、
保护层 8 项、S-curve 7 项通过，合计 **53 项相关离线测试通过**（不宣称运行了
整个仓库所有测试）。保护层与 S-curve 测试日志分别在 `tmp/motor-ident-current-regression.log`、
`tmp/motor-ident-scurve-regression.log`。构建/新增测试日志为 `tmp/motor-ident-*.log`。

## 人工分三阶段板测（此轮不执行）

共同准备：断开 12 V，MCU 供电，安装锁转夹具/防护，确认相序/角度/电流映射，
选择独立 candidate A，保留原 B。操作员全程在场，使用原 12 V/0.5 A 电源设置。
先按原流程校准、健康确认、输出关闭的 timing/stack/profile 预检；失败停住，
不试图绕过准入。先证明新增 hooks 条件下 50 us deadline/CCR late=0。

1. **Rs，需人工确认开始**：只接受
   `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`。400 ms 后验证输出关闭/最终状态，
   保存全部 row/原 fault/timing/RAM 证据。人工评估后新复位校准，再独立执行
   `RS 75 LOCKED CONFIRM`、`RS 100 LOCKED CONFIRM`。不自动连续升档。
   通过拟合且测量信噪比足够才进入下一阶段；否则只报告无效数据，不自动升流。
2. **Ld，再次人工确认 Rs 已验证与锁转条件**：新启动/预检后仅发
   `MOTOR TEST IDENT LD RS_VALIDATED LOCKED CONFIRM`。104 ms 后保存数据，
   检查无位移/保护/时序异常，独立确认 latch 对齐证据，host 拟合，人工批准才继续。
3. **Lq，再次人工确认**：检查夹具确实承受 q 轴转矩且有防护，新预检后仅发
   `MOTOR TEST IDENT LQ RS_VALIDATED LOCKED CONFIRM`。同样 104 ms，任何运动/保护
   立即结束，不自动重试。保存后统一计算候选 Rs/Ld/Lq 与指定 wc 的建议增益。

每次停止后关闭驱动电源再按原 A/B 流程恢复 B；数据先保存再复位。
本交付不自动烧录/运动/恢复启动选择，不为顺利完成测试放宽界限。

## 建模依据（仅审查参考）

- Microchip stationary PMSM model：
  https://onlinedocs.microchip.com/oxy/GUID-69278EBA-9F00-4CEE-8103-2998236856BD-en-US-2/GUID-70FB0D9D-8F89-4ABA-AB0D-E2E976C0E70E.html
- ST 手动参数配置：
  https://wiki.st.com/stm32mcu/wiki/STM32MotorControl%3AHow_To_manually_configure_the_motor_parameters

具体诊断包络与候选估计质量门是本项目的保守设计，不冒称厂家推荐的通用阈值。
