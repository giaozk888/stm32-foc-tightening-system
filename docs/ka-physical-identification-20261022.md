# Ka：先物理辨识，再按加速跟踪误差选择

本轮只准备 candidate A 的被动观察器、离线拟合和人工测试方案。
没有连接板子、刷写、复位、START 或正式参数写入。正式 A/B BIN 哈希保持不变。

## 模型与单位

```text
actual_acceleration_rpm_s = (measured_speed_end - measured_speed_start) / duration_s
mean(Iq_measured) - mean(Iq_friction_command) = Ka_identified * actual_acceleration_rpm_s + b
```

Ka 单位 A/(rpm/s)。不是 Ke，不乘极对数，不把 accel_ref 当 actual acceleration，
不把 IqRef 当实测 Iq。实际加速度来自现有实测/滤波控制速度的窗口差分；
仍包含速度估计滤波延迟，不声称是无延迟、外部仪器测得的轴加速度。

I_friction 是当前算法实际加到电流命令的补偿项，不是直接测得的物理摩擦力。
b 保留剩余静摩擦/负载与测量偏置。残差明显随转速变化，说明简单线性模型可能
漏掉粘性摩擦、负载或时间对齐影响，不自动把这些误差都归入 Ka。
闭环下有噪声自变量回归偏差，结果始终是 candidate，不能仅凭一个高 R² 宣称精确惯量。

## 采集

新 preset：`KaIdentificationDiagnostic`，继承现有受保护的正常速度状态机候选。
只把加速度前馈的 Ka 配为 0（框架仍 ON，保留 FRIC .105 A），以便先采无加速度前馈的数据。
PI、S-curve、摩擦量、限幅、角度、PWM pipeline、保护、IRQ 与正式 B 不改。

`FOC_KA_IDENT_DIAG` 默认 OFF，和旧 AAC/startup 诊断 ring 互斥，以免同时占用 RAM。
观察器只在现有约 1 kHz MotorControlTask 中、最终 Iq 命令发布后调用，不进入 ADC ISR。
实测 Iq 取现有 `foc_iq_A`（最近一个 FOC 的完整浮点读数），不是 20 kHz 全量电流均值。
按真实微秒时钟累计梯形积分，生成 24 个非重叠约 100 ms 窗口，覆盖约 2.4 s。
每窗保存起止时间、起止实测速度、实测 Iq 均值、摩擦命令均值、参考/实测速度均值和质量标志。
100 ms 窗口可减小瞬时尖峰影响，但不等于证明不存在电流偏置或混叠。

质量标志保留非有限输入、Iq 饱和、ADC 接受计数不推进、任务间隔超过 5 ms、
encoder sample 年龄超过 2 ms。它们只影响辨识样本准入，不改变控制/保护。
MonitorTask 每次取一个完整窗口，以 KAI T/S/I 三条同 seq 的 Pigweed 压缩消息输出。
每条真实 codec 测试 <=32 B；也可从完整 RAM 回读解析全部窗口，不依赖浮点日志精度。

## 离线拟合和质量检查

工具：`tools/ka_identification_report.py`，仅文件读取，无串口/刷写/启动入口。

```powershell
python tools/ka_identification_report.py --receipt RUN.json --elf foc2_app_a/build/KaIdentificationDiagnostic/foc2.elf
```

必须同一轮精确 BIN/ELF/Flash/RAM 身份匹配，且窗口发布序号连续。
真实板测 receipt 缺少原板测分类器的保护/时序/关断验收，不允许开启人工候选建议。
旧 AAC receipt 没有实测 Iq 窗口，不能被拿来伪装成新辨识数据。
测试用/导出格式另支持 `--windows-json FILE.json`，明确不是已验证硬件证据。

准入/可信度宏在 Python 文件中集中定义，只是分析门槛，不是电机保护阈值：

- 两端实测速度至少 10 rpm，排除零速、静摩擦和反向跨零窗口；正反方向分开拟合。
- 至少 8 个有效窗口，加速度标准差至少 20 rpm/s。
- 依据窗口时长加权最小二乘，拟合斜率 Ka 和截距 b；不按残差挑好看的样本。
- 报告 R²、残差 RMS、名义斜率标准误、残差-速度相关性。
- R² 至少 .6、正斜率、残差-速度相关系数绝对值不超过 .5，才是初步可用候选。
- 另合并相邻窗口做非重叠 200 ms 敏感性检查；斜率相差超过 30% 则降为不可信。
- 名义回归误差不是包含闭环/滤波系统误差的真实置信区间，仍需重复辨识。

若加速度近乎恒定，Ka 与 b 无法分开，必须报告激励不足，不能强制固定 b=0 得到数值。
既有 S-curve 已有加速变化/匀速，不在本轮为辨识偷偷改轨迹参数。

## 拟合后四档人工 A/B

只有新板测数据通过检查，才给出 .5/.75/1/1.25 倍 Ka_identified 的数值建议。
此时用现有 CMake 的 `FOC_ACCEL_FF_KA_A_PER_RPM_S` 指定参数，构建独立候选目录。
当前没有真实 Ka_identified，不能把假值编译成“已辨识候选”。

沿用现有 Ka 上限 .00025 A/(rpm/s)，最大参考加速度 200 rpm/s 时对应 50 mA。
超出此既有边界的倍率标记不可用，不修改边界。最终所有补偿仍统一进入 Iq clamp。
不扩展旧 `MOTOR TEST FF GAIN 0/25/50/100` 的含义，也不让它悄悄改用新基准。

建议新一轮同配方/同诊断负载，穿插 Ka=0 基线，四档各重复，再比较：

```text
J = integral_accel(abs(speed_ref - speed_meas) * dt) / integral_accel(dt)
```

现有全率 `SpeedAccelFf_Observe` 的加速相 MAE 正是该指标，不从 t_stable 才开始算，
不删除启动早期跟踪不好的数据。超调、Iq 峰值、积分峰值、饱和、FOC deadline/CCR late
作为约束；启动五时刻只作解释，不用于替代加速误差排名。不自动选定/写回最佳值。

人工板测先走原 A/B 流程：12 V 关闭确认后核验/仅暂存非活动 A，保留原 B，
另行确认上电/无报警/在场；校准、输出关闭时序预检通过后才允许一次空载 START。
本轮没有预授权自动四档运动；保护触发即停止，不自动重试。

## 构建与离线验证

- 新诊断 A：Flash/BIN 219828 B，静态 RAM 130600/131008 B（余 408 B）。
- 正常 A：Flash 219204 B，RAM 129560 B，SHA256
  `6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f`，字节不变。
- 既有 B 本地构建：Flash 228300 B，RAM 128792 B，SHA256
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，字节不变。
  本地 B 构建不等于改写物理板上保留的 B；本轮没有硬件访问。
- 新诊断 A SHA256 `cd9f970c4ddfb3ce8ddb9f2e13e1046441d5644bb05df01e493f726d570fb8be`。
- 与正常 A 对照均 13 条既有 unused/RWX warning；新增观察器无新增 warning/error。
- 新辨识 11 项、现有 speed 系列 88 项、gain 编排 4 项、startup 5 项，共 108 项通过。
  C 观察器 -Os/-O2、真实 Pigweed codec、正反向已知斜率/截距、NaN/饱和/时间回绕/坏间隔、
  激励不足、漏掉速度相关负载、旧限幅、正式 A/B 哈希和控制 owner 逐函数一致性均覆盖。
- 尚未新板测，没有真实 Ka_identified，没有承诺新增观察器后的实机时序已经通过。
