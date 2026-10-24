# 0.5 倍 BEMF 正常 A 与机械辨识 / DOB 旁路准备

## 本轮范围

用户选择 BEMF ψf 的 0.5 倍，已固定到新正常 A 预设 `TighteningBemfHalfCandidate`：`FOC_BEMF_PSI_WB=0.00034866`、BEMF 默认 ON，Ka 固定为 `0.000046875 A/(rpm/s)`。旧预设、旧镜像和正式 B 都保留，未覆盖历史实验身份。后续记录直接使用 Ka 数值，不用倍率代替。

另有 `MechanicalIdentificationCandidate`，只在同一正常控制上增加被动二进制采集。没有新轨迹、注入、自动 START、自动扫速或参数写入。DOB 是已离线测试的**只读旁路模型接口**，尚未接入实时控制，也没有生成实测 J/B/Kt。

本轮没有刷板、复位、改变启动选择、注入电流或启动电机。上一轮板端 B1007/输出关闭状态未被本轮工具操作改变。

## 不把前馈调节值当成物理磁链

当前幅值不变 Clarke/Park 为 `Iq=-Ialpha*sin(theta)+Ibeta*cos(theta)`，电机 p=10、机械方向定义不变。Id 近零时，采用 dq 电流定义的总转矩常数：

`Te = Kt_dq * Iq`，`Kt_dq = (3/2) * p * psi_physical`，单位 Nm/dq-A。

这不同于一些文档定义的单相 `Ke_phase_peak=p*psi` 或以 RMS 电流定义的厂家 Kt，必须先明确单位和定义。[MathWorks PMSM 模型给出了相同幅值不变 Park 及转矩公式](https://www.mathworks.com/help/simscape-electrical/ref/pmsmdq0.html)。

`psi_effective=0.00034866` 是本次人工选择的前馈系数，不是新测得的物理磁链。不能据此自动把 Kt、J 或 B 减半。即使原命令电压估算 `psi=0.00069732` 对应模型 `Kt_dq≈0.0104598 Nm/A`，它仍是未独立校准的候选，不在本轮当成标定常数使用。

## 可辨识性与拟合

机械方程：`Kt*Iq = J*domega/dt + B*omega + Tc*sign(omega) + load/bias`。

仅观察 Iq 和机械转速时，把 Kt/J/B/Tc 同比例放大不会改变测量关系，不能独立确定这四个绝对量。先拟合：

`Iq_lp20 = a*actual_alpha + b*mean_omega + c*sign(omega) + d`

- `a=J/Kt`，A·s²/rad。
- `b=B/Kt`，A·s/rad。
- `c=Tc/Kt`，A。
- `d`，A，承接常量电流偏置/等效载荷；不是凭空认定的外部负载。
- `omega` 是机械 rad/s，`alpha` 是机械 rad/s²；来自实测速度端点及实际 dt，不用 accel_ref，不额外乘极对数。
- 使用实际测量 Iq，而不是 IqRef；不先减掉“摩擦补偿命令”，避免把已真实产生的摩擦转矩误从模型中扣除。

有独立 Kt 后才输出 `J=a*Kt`、`B=b*Kt`、`Tc=c*Kt`。`--kt-calibrated` 必须同时给正有限数值和明确来源，未给时绝对参数保持 null。Kt 不会从上述回归中假装独立辨识出来。先获得独立转矩常数再由电流换算机械转矩，也与[官方机械辨识流程](https://www.mathworks.com/help/simscape-electrical/ug/parameterize-a-pmsm-from-measurements.html)一致。

## 采集路径

- `firmware_common/mechanical_identification.h/.c`：ADC 单写者发布 seq、软件 pair-read 时间、发布完成时间、Id/Iq 和电压饱和状态；任务读者最多尝试两次版本校验，不屏蔽 ADC IRQ，不无限自旋。
- `main.c`：原 FOC 结果提交后只增加被动发布；不改变 PI/SVPWM/一拍 PWM pipeline。已有约 1 kHz 编码器处理路径汇总诊断样本。
- 每约 64 ms 形成一帧，128 帧最多覆盖约 8.192 秒；buffer 到上限冻结、不滚动，最后不足一帧的尾段不捏造。
- 每帧 36 B：encoder end_us、ADC seq、实际 dt、观测点数、机械 raw delta、flags、filtered omega end/mean、原始 Iq 时间均值、20 ms 匹配 LPF 的 Iq 时间均值、mean abs Id。
- 128 帧及元数据 4712 B，电流发布 28 B；诊断 RAM 总增量以链接结果为准。
- 正常 START/速度模式进入时只重置计数与积分状态，不在高优先级 IRQ memset 整个数组。停机后读完整 RAM，禁止 ISR printf/UART。
- 采集是每次任务观测时的最新完整 accepted ADC 快照，不等于收齐全部 20 kHz 电流样本；source_us 不是模拟采样孔径时间，encoder 时间是 SPI 接收时间。
- 拟合 Iq 诊断 LPF 使用与现有控制速度相同的 20 ms 变量 dt 一阶形式；只影响诊断副本，不是新控制滤波。实际编码器中值处理、闭环测量噪声和非线性摩擦仍可能使拟合失败。

## 离线工具与资格门禁

`tools/mechanical_identification_report.py --receipts <run1.json> <run2.json> ... --elf <同版本foc2.elf>`。

可选：`--kt-nm-per-dq-a <值> --kt-calibrated --kt-source <独立校准来源>`。工具只读文件、输出 JSON，无串口/SWD、无参数写入。

解码校验同次 BIN/ELF/Flash/RAM 哈希、RAM ABI/边界、时间戳回绕、ADC 序列和首尾一致；拒绝重复 receipt 或相同 RAM 假冒独立重复。关断寄存器、预检、独立故障快照、CUR_CONFIRM、encoder、deadline、CCR late 等必须合格；仅原空载流程超时允许作为非独立保护终止。

仅做预先定义的数据准入，不按残差挑最好点：

- 丢失/陈旧/不连续/饱和/非有限/异常 dt 的帧不进入拟合。
- 异常帧后固定两帧作为诊断滤波恢复窗，不拼接不连续片段。
- 分析门限：至少 20 rpm、mean abs Id≤0.05 A、同窗不反向；这些是辨识样本准入，不修改电机保护。
- 加权四变量最小二乘，列 RMS 缩放后检查实际矩阵秩和无穷范数条件数，不用 ridge、符号翻转或自由时间平移强行修复。
- 需要正反向、足够速度/加速度变化、至少 40 个有效窗；检查正 J/Kt、非负 B/Kt/Tc、R²≥0.7、残差 RMS≤0.03 A、条件数≤1e5。
- 64 ms 与相邻双窗 128 ms 拟合交叉验证，a 变化不超过 30%；至少三次独立运行，逐 session 留出预测检查。单方向稳态只能给部分线索，不能宣称 J/B 完整标定。
- 不合格时仍完整报告 accepted/rejected、理由、系数、残差与问题，但 `normalized_qualified=false`、`dob_shadow_ready=false`，绝对参数不输出。

## DOB：只准备旁路，不加入控制

`firmware_common/mechanical_dob_shadow.h` 提供经过 native 测试的纯 C 观测接口：

`disturbance_A = Q(s)[Iq - b*omega - c*sign(omega) - d] - a*s*Q(s)*omega`，`Q(s)=g/(s+g)`。

两条支路同一离散极点，用滤波状态实现微分，不直接对 noisy speed 作裸差分。正值表示超出已建模惯量/摩擦的正向等效负载电流，而非真实 Nm 载荷；若要 Nm，还要独立 Kt。

未标定、零速附近、无效样本、坏 dt、非有限数或保护故障时复位/无效；经过五个时间常数预热才给 valid。示例测试使用 5 Hz，仅是旁路算法验证，不是新正式控制带宽。接口没有任何 Iq/PI/PWM 写路径，也没有实时自动装载参数；当前诊断镜像只采集，未在实时任务调用这个 observer。

后续应先用合格模型离线回放，再做不参与控制的 shadow 观察；确认正负载方向、延迟、噪声和与现有摩擦前馈不重复后，另行设计限幅、总输出 anti-windup 与保护链，再考虑 DOB 闭环补偿。本轮没有这一补偿效果。

## 构建与验证

| 构建 | Flash B | RAM B | RAM 剩余 B |
|---|---:|---:|---:|
| TighteningBemfHalfCandidate（正常 A） | 211584 | 124016 | 6992 |
| MechanicalIdentificationCandidate（被动采集 A） | 212888 | 128896 | 2112 |
| 独立目录 MechanicalReviewB（原本地 B 配置复编） | 228300 | 128792 | 2216 |

未缩减 heap/线程栈。采集 A 新增 Flash 1304 B、RAM 4880 B；实板 FOC 时间及最小栈余量尚待重新测量，不能用离线编译代替 50 us 验收。

- 正常 A BIN SHA256 `58f68d3735529f356803dc79fc2e1f609663b92516aff5318773a00110835d90`。
- 正常 A ELF SHA256 `bd24bfb09d1b157d9d72da2d6699e525cdbedcab785731c7b470e3aeb65d8673`。
- 采集 A BIN SHA256 `3f2a871fa6cf6a1d6a3741226f4a8735e2d9d460354122f66ab8f34b2950450f`。
- 采集 A ELF SHA256 `893f75b5de8b988bfe4a71a2c41e810ffe1ed5dfb2531118502e4c40dda5c6dc`。
- B 复编 BIN SHA256 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，与原本地稳定 B 完全相同，没有覆盖旧目录。它不等于板上 227964 B 原 B 的版本；板上 B 本轮未访问、更未刷写。
- 121 项定向离线回归通过：机械模块/候选 12、原 BEMF 8、Ka025 11、flux-gain 9、speed 系列 81。
- 覆盖已知合成机械模型恢复、不可辨识/单方向/恒速拒绝、64/128 ms 一致、独立 Kt 必需、坏样本/残差不可挑选、时间戳回绕、数组冻结/重置、DOB 稳态与匀加速、故障/NaN/零速/未标定清空。
- 对照正常 A 与采集 A：除被动 publication/capture 插桩，控制代码 token 不变；ADC IRQ、CCR pipeline、guard、power stage、encoder angle、FSM 不变。IRQ、ADC timing、encoder DMA、zero calibration、FSM 目标对象逐位相同。
- 没有新增 warning 类型；仍有历史 unused 符号与 RWX 链接 warning，不能称为零 warning。

## 下一轮人工步骤（本轮未执行）

1. 驱动板断电后仅暂存非活动 A，完整回读、保留 B；现场转轴解锁、空载固定和防护、12 V/限流 0.5 A、可立即断电。
2. 上电后先校准和输出关闭时序预检，确认新发布插桩仍满足 FOC/CCR 和线程栈余量；不通过则不 START。
3. 准备经审查的空载正反向多速度采集（优先 ±100/±200/±240 rpm，仍在原 300 rpm 边界内），兼顾加速、稳态与受控减速；现有固定 240 rpm 板测脚本不能未经适配就宣称完成这个多点批次。每次只用原保护/轨迹，不靠提高阈值获得可拟合结果。
4. 保存同版本 ELF/Flash/RAM/receipt，离线拟合全部合格样本，先看可辨识性、条件数、残差及留出验证；质量差则保留数据、报告失败，不硬算正 J。
5. 若需要绝对 J/B/Kt，另做独立转矩常数校准或独立已知惯量/转矩参考测试；电流/编码器两路本身不足以把三者独立分离。
6. 模型合格后另行人工授权 shadow 板测；本轮不接入 DOB 控制、不改速度/电流 PI、不改保护、不刷 B。
