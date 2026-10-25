# 第2阶段：RUNDOWN负载降速，独立Simulink候选

本轮只新增软件仿真目录功能，不修改固件、正常A/B、PI参数、配方或保护阈值，不连接硬件。
不宣称真实电机、接触冲击或拧紧质量已验证。

## 位置与因果顺序

```text
上一周期DOB/75ms分类完成帧
             ↓
原tightening_intent_fsm → base ControlIntent → LoadSpeedScheduler
                                             ↓
                                    selected_target_rpm
                                             ↓
                             原SpeedScurve → 原速度环主机适配
                                             ↓
                          acceleration FF + friction + 固定DOB0.25
                                             ↓
                       总Iq限幅 ±0.50A → 50us延迟 → 独立机械模型
```

调度器不回写FSM状态或原配方，不消费仿真负载真值/接触真值，不修改Id/Iq反馈。
原C的FSM、轨迹、前馈、摩擦、DOB、质量门控、有界补偿与AW计算继续使用。
速度PI编排复用既有 `dob_host.c` 主机适配（不是整个MCU/FOC仿真）；实际电流PI、dq电压和BEMF电压未显式模拟，电流执行器是1ms一阶滞后的声明假设。

## 本轮固定策略（运行前声明）

- 仅 `TF_RUNDOWN` 有权限。RUNDOWN_START、CONTACT_CONFIRM、TIGHTEN、HOLD和故障/STOP保留原FSM目标。
- 原RUNDOWN目标240rpm。可信负载等级HIGH，或可信RISING且方向归一化负载均值≥10mA，累计30ms合格证据后选择120rpm。
- 使用原分类器门槛HIGH25mA、LIGHT10mA、趋势±20mA/s；这些是未实际标定的软件初值，不是扭矩保护值。
- 恢复到LIGHT且不处于RISING，累计200ms合格证据、已低速至少300ms后选择原目标。
- 单帧失效不作为零负载，不累计驻留，短时保持原选择；连续200ms没有有效分类就取消降速权限，退回原FSM目标，由同一S曲线转移。故障/STOP仍直接优先关断。
- 无效回退到240rpm是本轮明确的候选策略，不保证对所有高负载最优，必须检查其反复切换和饱和表现。
- 目标幅值不超过原目标；降速目标为 `min(abs(base), max(120, contact_rpm+12))`，保留方向。当前CONTACT仍20rpm，目标不会主动降到接触判据附近。
- 目标变化调用原 `SpeedScurve_Step`，不Reset轨迹；200rpm/s、1000rpm/s²不变。
- PI .003/.020、积分限幅.35A、Ka .000046875、摩擦.105A、DOB gain .25、补偿25mA、总Iq .50A保持不变。
- 观察器采用已选3τ/2Hz、75ms分类、饱和连续估计。未验证成功的短低速快速恢复试验不与本阶段叠加，OFF/ON使用同一观察器。

原FSM完整运行，接触仍要求已建立运动、实际低速≤20rpm、电流需求≥300mA、250ms驻留；不因调度降速临时屏蔽CONTACT。
若原判据对主动降速产生误接触，保留为失败，不能先修改判据掩盖。
配方仍8秒rundown、20000°行程和12秒会话；晚接触可能因降速错过原限时，也要计入失败。

## 仿真与评价

每个场景OFF/ON配对各10次，种子1～5/61～65，外部噪声和负载函数相同。
覆盖无载、阶跃、斜坡、卸载、孤立尖峰、持续Id异常、400ms来源缺口、强噪声、历史实测噪声注入、反向、两个不同接触位置、STOP和故障。
历史噪声记录1～3用于前5个种子，4～5用于后5个；不是已知真实负载或真实接触真值。

独立模型在50us更新归一化机械动力学，参数J/Kt、B/Kt各±10%、库仑项±5%，OFF/ON同一参数；模型没有从DOB输出反向构造负载。
接触采用位置固定的理想单向机械挡块，位置每对随机±10%，只能验证逻辑与名义运动，不代表真实螺纹、弹性扭矩或接触冲击。

输入From Workspace的时间列统一提前1ns以避开二进制浮点边界落到前一行；实际消费的15个外生量逐点与原数组严格比较，保持1ms控制周期不变。
首次两个输入对齐失败保留在独立结果目录，未当作有效对照。

同时记录base/selected/shaped目标、实际速度、DOB/质量/分类证据、调度原因/驻留、全部FSM状态与CONTACT进度、Iq/积分器/饱和、真实位置/负载及接触时刻。
评价必须包括接触前速度、完成/超时/漏接触、总行程、原240rpm缺口、跟踪误差、Iq峰值和饱和时间；不能只凭更低目标的跟踪误差宣称改善。
运行后输出每轮CSV.gz、指标均值/标准差、配对差和关键曲线，保留全部失败。

## 入口

- 原生策略：`simulation/dob_simulink/native/load_speed_scheduler.h`
- 控制/FSM适配：`.../native/load_speed_host.c`
- 独立plant：`.../native/load_speed_plant_sfun.c`
- 构建：`tools/prepare_load_speed.py`、MATLAB `build_load_speed`
- 运行：MATLAB `run_load_speed('full')`
- 独立审计：`tools/report_load_speed.py <结果目录>`
- 绘图：MATLAB `plot_load_speed('<结果目录>')`

下一步只有在本轮审计结果和取舍明确后，才决定是否准备默认关闭的MCU候选；本轮不烧录。
