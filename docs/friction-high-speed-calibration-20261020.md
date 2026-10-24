# High-speed running-friction diagnostic: 200/240/260/280rpm

Explicit user request: collect four higher speeds in one batch. Retain signed
directions and three planned repetitions (24 independent points), compare all
failures as well as clean steady points. No automatic Iq increase or friction
parameter write.

## Scope / preserved evidence

- New preset `FrictionCalibrationHighSpeedDiagnostic`; old diagnostic BIN/ELF
  remains immutable in its original build directory.
- `FOC_FRICTION_HIGH_SPEED_GRID` defaults OFF and requires the exclusive A
  calibration diagnostic. No formal B changes.
- Sole command-range change: diagnostic `MOTOR_SPEED_API_LIMIT_RPM`250 ->280.
  Both generic and protected independent overspeed trips remain300rpm.
  Current command limit stays+/-0.50A, hardware/4A current/encoder/time protections
  and current discriminator/CUR_CONFIRM/PWM pipeline remain unchanged.
- Closed allowlist: +/-200,+/-240,+/-260,+/-280rpm. No arbitrary command or300rpm
  motion request. Native test executes the actual preprocessed SetSpeed body
  proving260/280 are not silently clipped to250; requests above280 still clamp.
- New read-only `MOTOR TEST FCAL LIMITS` must return API_RPM=280/TRIP_RPM=300/
  IQ_LIMIT_MA=500/GRID=HIGH at every boot before motion. Per-point requested RPM
  is also checked in every FCAL status reply.
- Original five-second drive / seven-second stop bound / twelve-second independent
  lease, speed stability/quality criteria and NOROTATION guard unchanged.
- FRIC OFF, acceleration FF ON, existing S-curve and PI unchanged. Only zero-
  acceleration/reference-at-target windows can enter the friction estimator.
- Isolated process NO_ROTATION and measurement failures remain recorded and
  allow a fresh protected next-point boot; electrical/current/encoder/timing/
  uncertain-stop failures still abort the grid.

## Builds / offline verification

New A: Flash212964B /229376B, RAM129040B /131008B. Existing unused/RWX warnings
remain, final link successful. Four new high-grid tests and19 existing diagnostic/
runner/comparison tests passed. Frozen source checks compare actual ADC/FOC,
current/encoder guard, PI, PWM pipeline and task owner against old diagnostic;
only requested SPEED input/reference clamp constant differs250 ->280.

BIN SHA256 `f4231c660daab2cbc3dc955bee7057416c3e0b041da6d74471e0959159ab73d6`.
ELF SHA256 `7f0f33ca6223d6d5e004c09bbde8f2fc639716eaea3792c621d9d83b8eed0c7c`.
Old calibration BIN remains `a23a7c8760e92cd498d3753065aad12a220ce66514aeac245421869a24a117f0`.
Formal FR1 A remains `c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8`.
B build remains `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`.

`tools/friction_high_speed_board.py` uses the shared tested runner with its own
exact BIN/ELF pins and exact halted B792 baseline, not guesses at mutable metadata.
Default execution is files only. Resume data from old speed grid is not used in
this new high-grid batch; all24 measurements are new.

## Hardware preparation

User combined-confirmed12V OFF, MCU powered, empty fixed motor, unchanged signal/
power wiring,12V/0.5A supply and present operator able to remove power throughout.
Inactive A only written, verified and independently fully read back:
`tmp/friction-cal-stage-1792492836433994500.json` PASS. B/boot/config/metadata
unchanged. User separately confirmed12V ON/no alarm/operator present before
launching the signed24-point high-speed batch. No boot actuation.

## 实测结果与恢复（2026-10-20）

24 个计划点均已处理：23 次实际驱动，1 次明确准入拒绝、未启动。
每个转速/方向计划重复 3 次。每次驱动 5 秒，再沿既有停止斜坡退出。
摩擦补偿全程 OFF；未自动写入任何摩擦参数。

|目标 rpm|平台稀疏采样平均速度 rpm|平台稀疏采样平均 Iq A|严格整段合格/计划次数|
|---:|---:|---:|---:|
|+200|+197.73|+0.1569|0/3（2 次运行、1 次未准入）|
|+240|+235.97|+0.1585|0/3|
|+260|+257.42|+0.1693|0/3|
|+280|+278.78|+0.1642|3/3|
|−200|−196.65|−0.1365|0/3|
|−240|−237.62|−0.1646|0/3|
|−260|−258.58|−0.1579|2/3|
|−280|−278.19|−0.1657|2/3|

以上平台平均来自 10 Hz 完整 FRC 帧，要求 reference=target 且 accel_ref=0；
包含未通过整段稳定性验收的数据，不能当作全速率稳态估计或峰值。
最终分类：7 STEADY、16 NOT_STEADY、1 NOT_ADMITTED。平均转速接近目标
并不意味着速度波动、settling、reject 比例等整段指标全部合格。

严格合格的 1 kHz admitted 窗口如下（电流均值不同于上表的稀疏平台均值）：

|转速/重复|有效时间 s|mean Iq A|mean Id A|
|---|---:|---:|---:|
|+280 / 1|2.593|+0.167176|+0.001167|
|−260 / 1|2.422|−0.164398|−0.001151|
|−280 / 1|2.343|−0.167323|−0.000478|
|+280 / 2|2.345|+0.168231|+0.000461|
|−260 / 2|2.436|−0.161608|+0.001094|
|+280 / 3|2.832|+0.168070|+0.001863|
|−280 / 3|2.316|−0.168245|+0.001042|

### 准入拒绝与批次续采

第 17 个计划点（+200 第 3 次）返回明确关联的 `7805 ERR FCAL NOT_READY`。
原 runner 停止，没有重发启动。回读证明 used/queued/active/seen/valid 全为 0，
first-fault invalid、所有 live guard 清除、encoder valid、输出关闭且 MCU 停住。
因此该点只标记 NOT_ADMITTED，不计作实际驱动，不声称其摩擦数据有效。

host runner 增加严格的明确拒绝分类及同镜像、同会话、停机收据验证的续采。
未改变固件或保护，不重试拒绝点；从第 18 个计划点继续剩余 7 点。
未知 ACK/超时、任何真实 current/encoder/timing fault 仍中止。

原始批次：`tmp/friction-cal-run-1792492902358858000.json`。
最终完整批次：`tmp/friction-cal-run-1792493595911313700.json`。
离线统一比较：`tmp/friction-high-all-comparison.json`。
原始分点 Flash/RAM/UART 收据仍保留，未覆盖。

### 拟合结论：正式未通过，探索性估计不写入控制

严格数据正向只有 280 rpm，缺少至少两个匹配的正负速度幅值，因此正式
`friction_fit=null`，不能用它独立可靠地分离库仑项、黏性项和偏置。

另作敏感性分析：纳入两个整段 QC 未通过、但拥有超过 2 秒有效 admitted
子窗口的点（+260 第 1 次、−280 第 2 次），共 9 个窗口，在 260/280 rpm
匹配幅值上用实际 measured mean speed 拟合：

`mean_Iq = I0 + Ic * sign(speed) + Bi * speed_rpm`

- I0 = +0.000143 A
- Ic = 0.104919 A（约 0.105 A）
- Bi = 0.000225029 A/rpm
- 拟合残差 RMS = 0.000742 A（不是参数置信区间）

这只是 EXPLORATORY sensitivity，`calibration_accepted=false`。
两个整段失败标志未被修改；260–280 rpm 范围窄，向零速外推不可靠。
不能据此宣布 breakaway current，也不能将电流模型当作已标定 Nm。
现有 I_FRIC=0.20 A 未改，未自动选择新 I_FRIC/deadband。

### 时序、保护与最终状态

- FOC wall max：31.958824 us；deadline miss：0。
- actual CCR late：0；最小 actual margin：13.529412 us。
- CUR_CONFIRM：2546 enter / 2546 clear / 0 fault。
- 本批无真实电流/编码器/时序保护故障；一次安全准入拒绝单独保留。
- 4 项 high-grid 测试通过；runner/comparison/model 相关 23 项测试通过。
  新增 host handling 没有更改控制数学、保护阈值或固件镜像。

用户确认 12 V 关闭后，通过原 bootloader 流程仅恢复 B 启动选择：
`tmp/friction-cal-restore-1792493964050693700.json` PASS。
metadata generation=796，confirmed B，pending=0；B length=227964，CRC=627317606。
全 Flash 回读 SHA256：
`f6e511212486bc4804265c88cd8fb21d9019664fd0e704a4933e889fd066fb5e`。
A/B 应用与私有区保持恢复前不变（仅合法启动元数据更新），B 应用未运行。
停在 B 入口 0x08051028，VTOR=0x08040000，SD=0、BDTR=0、CCER=0，MCU halted。
恢复阶段 motor commands=0；不再测试、不自动运行电机。
