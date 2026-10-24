# DOB shadow 首轮人工空载板测

## 结论

**运动采集与安全关断正常；DOB 有效覆盖率不足，未验收为可靠扰动估计，更未启用补偿。**
本轮仅一次正向600 rpm，未运行反向/负载干预/闭环DOB，也未重试、改PI或提高限幅。
用户在整个测试期间确认12 V/限流0.5 A、空载固定/解锁/防护、可立即断电。

## 镜像与凭据

`MechanicalDobShadowCandidate`，BIN SHA256
`74d53cf4e47743ccfa8bfbe5ca73ed4d58dcc0332ca59b785bfe8b54bb84e770`；
ELF SHA256 `6ab8d8f68708e9b65dec79a8bac3a1319080068f506823d7586bb3dd63003654`。
没有重新编译或改动已审查固件，候选参数见 `docs/mechanical-dob-shadow-candidate-20261023.md`。

- OFF暂存：`tmp/mechanical-ident-stage-1792715330064926900.json` PASS。
  两次完整回读，B/boot/config/private未变；activation=false、motor_commands=0。
- 批次：`tmp/mechanical-ident-batch-1792715425621348100.json` PASS，只有一个点。
- 原始单次：`tmp/mechanical-ident-run-1792715425732415200.json`，保存完整Flash/RAM及hash。
- 离线DOB解析：`tmp/mechanical-dob-shadow-report-1792715425732415200.json`。
- 用户确认关闭12 V后恢复B：`tmp/mechanical-ident-restore-1792715560592626800.json` PASS。
  generation1043、active=B、pending=none、VTOR=0x08040000，SD/BDTR/CCER=0、CPU halted；
  `all_app_private_unchanged=true`、`b_application_not_run=true`、`motor_commands=0`。
  原物理B仍为227964 B / CRC627317606，未重刷B。

receipt中的PASS只表示**该次采集/保护/关断证据完整**，不是DOB模型/扰动补偿验收通过。

## 运行与保护证据

- 零点valid=4000、reject=38、total=4040、max consecutive reject=2，PASS。
- 校准与时序预检通过，电流准入age=33 µs、failed=0、没有NOT_READY；仅一次RUN。
- 运行前后MotorCtrl已采样的最低空闲栈均为2520 B。
- 显式`MOTOR TEST MECH RUN POS 600`，原轨迹/5 s驱动及受控减速，约8.12 s自然完成。
- 机械捕获125个积分bin，跨度8.069002 s；终端位置约17803.10°、速度回0。
- 已记录bin端点的最大filtered speed=603.336 rpm（不是所有原始速度点的绝对峰值）。
- 描述性稳态选择：bin mean距600 rpm≤12 rpm，且端点平均加速度绝对值<5 rad/s²，
  14个bin/0.903087 s，时间加权平均598.653495 rpm、Iq=0.223759760 A。
  此选择只用于描述运动表现，不重辨识或挑残差改变DOB参数。
- FOC wall max=33.252941 µs、deadline miss=0、CCR late=0、最小实际CCR余量15.170588 µs。
- first fault=0；encoder timeout/DMA error/schedule miss/control stale均0。
- CUR_CONFIRM enter/clear/fault=129/129/0。
- outer trace最大entry gap1089 µs、core155 µs、observe148 µs；不同最大值不相加冒充单次耗时。
- DOB自身计算wall max=50 µs，包含IRQ抢占，属于约1 kHz任务额外计算；不是20 kHz FOC的50 µs deadline。
- 终端`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`，实际寄存器MOE/AOE关闭、CCER=0、CPU停住。

旧`LEGACY_FCAL_PASS=0`不能用来判断DOB是否通过：保留的旧FCAL健康判据要求FRIC OFF，
这轮独立机械诊断沿用FRIC ON；该旧质量结果不等于保护故障，也没有被拿来自动继续下一次。

## DOB实际观察结果

启动前读回四参数/2 Hz/20 rpm均匹配；所有查询均`SHADOW=1 FEEDBACK=0`。
Ka=0.000046875 A/(rpm/s)、ψ=0.00034866 Wb、摩擦前馈0.105 A不变。

|指标|结果|
|---|---:|
|总观察次数|8120|
|有效观察次数|696|
|有效覆盖率（含启动/减速的全程分母）|8.5714%|
|质量reject次数|545（6.7118%）|
|无效但非reject次数，预热/低速等|6879|
|仅有效点的正向D_A均值|+0.000236347 A|
|仅有效点的最大abs D_A|0.012738753 A|
|有效负向点数|0（本轮未测反向）|

均值/峰值只覆盖696个被准入的点，不能把剩余7424个无效点当作0，也不能声称是整段稳态残差。
空载均值接近0不证明负载扰动的方向/增益/延迟正确，更不是Nm扭矩精度。

稀疏UART共22组：主视图WARMUP=15、ID=4、ZERO_SPEED=1、VALID=1、OFF=1。
稀疏查询不能代替每个1 kHz观察点，也不能与相邻ADC子查询强行拼成同一帧。
全局696有效点来自板端连续计数，不是根据UART那一个VALID主视图估算。

最终16点RAM尾窗约0.967968 s：WARMUP=11、ID=2、ZERO_SPEED=3，全部无效。
尾窗在减速末段，不代表完整驱动期；current因STOP标OFF，历史ring保留。
已观察到Id瞬时波动（例如稀疏读回-0.262759 A）及ID模型域失效。
ID按独立20 ms低通的abs Id>0.05 A判定，而不是单帧Id阈值；失效复位后需约398 ms连续预热。
因此“Id模型证据不满足→观察器复位→重新预热”确实发生，能解释有效覆盖率偏低的重要部分。
但现有日志**没有每种reject的全程累计计数**，不能断言545次全部为ID，或排除早段短暂时序/电流质量问题。
没有因此修改PI、滤波/复位策略、Id准入条件或任何保护。

## 本轮工具接入与离线复核

新增`tools/mechanical_dob_board.py`及6项wrapper测试：
只接受一次显式POS600、核对DOB身份/四参数/FEEDBACK=0，再调用原readiness/RUN owner；
沿用原功率关闭校准/时序/栈预检、保护、STOP/ANALOG SAFE/完整捕获与原B恢复。
未复用旧镜像stage凭据冒充新镜像，失败不自动重试或切到反向。

检查真实时序时，补正了**仅离线decoder**的一个假设：ADC软件pair-read可能晚于encoder receive，
例如晚114 µs；这不等于ADC“来自未来”或必定陈旧。
固件一直分别对同次captured observed_us检查encoder age≤2000 µs和ADC source age≤200 µs。
因此decoder应检查有符号source−encoder∈[-200,+2000] µs，而非把encoder−source当无符号ADC age。
同时保留publish−source≤100 µs、同镜像/同session/ABI/安全闭合检查；固件和安全门限没有变化。
ABI没有保存observed_us，故只能检查该必要关系，不能离线复原精确runtime age。
本次尾窗全无效，原解析并未依赖错误假设通过有效帧；补正覆盖未来真实VALID帧解码风险。
新增真实“ADC在encoder后”及timer wrap用例，实际C与decoder均验证。

本轮26项相关wrapper/监控/decoder/旧恢复链回归通过，见`tmp/mechanical-dob-board-regressions.log`；
候选固件既有241项回归与构建结论仍见候选文档，固件hash未变。

## 建议下一步（本轮未实施）

先补每种无效原因的计数/持续时间、最后有效/复位时刻，以及abs Id滤波值，
区分Id域持续超限、真实样本质量/时序异常、正常低速退出与预热损失。
根据完整证据再讨论电流波动来源或观察器恢复策略，不直接取消准入、缩短预热、提高阈值或接入Iq。
之后复测shadow的有效覆盖率及正反向一致性；未达标前不进行DOB闭环效果对照。
