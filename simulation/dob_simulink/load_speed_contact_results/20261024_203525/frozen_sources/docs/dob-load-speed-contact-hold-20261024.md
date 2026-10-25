# 负载降速：CONTACT_CONFIRM 阶段边界修复

本轮只优化候选 A 的目标选择边界，没有烧录、复位、调试连接或启动电机。正式 B 源码和板上 B 均未修改。
软件结果不能作为真实电机性能验证。

## 原因与修改

上一轮实机在 6.070019 s 进入 CONTACT_CONFIRM，原策略仅允许 RUNDOWN 降速，因而将已有 120 rpm 选择取消、恢复 240 rpm。
这不是负载已经解除，而是调度器把状态切换误当作降速许可失效。S 曲线继续限加速度，但目标会在接触候选期间反向改变。

新增默认关闭选项 `FOC_DOB_LOAD_SPEED_CONTACT_HOLD` 和独立构建 `DobLoadSpeedContactHoldCandidate`：

1. RUNDOWN 仍按原高负载／上升趋势条件选择 120 rpm；CONTACT_CONFIRM 不能自行新建降速许可。
2. 已选择 120 rpm 时，未确认的 CONTACT_CONFIRM 保留该目标，不因分类短暂失效恢复 240 rpm。
3. 候选取消回 RUNDOWN 时重新确认负载。有效 LIGHT 仍需原 200 ms 连续证据和原 300 ms 最短降速时间才能释放。
   若分类尚未恢复，沿用原 200 ms 失效时长作为有界等待，超时按原失效回退，经 S 曲线恢复原目标。
4. 不伪造 last_good、有效样本、DOB 预热或滤波时间。保持的是速度目标选择，不是过期的 DOB 电流补偿。
5. 原 FSM 确认接触后的零电流 NEUTRAL、TIGHTEN/HOLD 电流控制、STOP 和保护继续拥有优先权。
   MCU 原钩子仅在 SPEED 分支调用；非 SPEED 期间留存的调度诊断字段不是功率状态证据。下一 SPEED 周期按原阶段重新评估。

CONTACT 20 rpm／300 mA／250 ms、8 s rundown 超时、12 s 板端限时、20000° 行程、MCU 500 rpm 超速和总 Iq ±0.50 A 均不变。
PI、Ka=0.000046875 A/(rpm/s)、摩擦、DOB gain=0.25／补偿上限±0.025 A、2 Hz／3τ、75 ms 分类以及 S 曲线参数不变。
不改变 FOC、电流采样、PWM pipeline、CUR_CONFIRM、CURRENT_INVALID、保护与 IRQ 优先级。

## 测试与构建

- 原生回归 28 项通过：纯策略、真实 MCU 选择函数、完整原 C FSM、接触取消、确认后的 NEUTRAL、STOP／故障、反向、快照恢复、重复 epoch、日志环形覆盖和审计反向注入。
- 原 V1 镜像和工具回归另 4 项通过；V1 镜像哈希仍为 `06b0c15943965e06ed409ad4190adf9fda78ae20c4f8592c66cfb518d0e23160`。
- 新 A 编译通过：Flash 228712/229376 B，链接 RAM 布局 130968/131008 B。
  相比 V1 增加 Flash 360 B、状态 RAM 8 B，链接 RAM 布局仅余 40 B；运行时栈余量和 FOC 时序尚未重新板测。
- 未改源码的 B 使用 `MechanicalReviewB` 做离线编译检查，通过；该离线产物没有写入板上 B，也不冒充板上 B 的原始二进制。
- 已有 unused-function/variable 和 RWX LOAD 段链接警告仍存在，没有新增负载调度模块编译错误。

日志新增 CONTACT_HOLD／CONTACT_REACQUIRE 原因、阶段保持与重新确认计时。
状态结构 68 B；借用的原分类记录尾区仍为 200 B，事件改为 48 B，保留第一次和最后三次事件。
V2 magic=`0xD1500002`，解码器为 `tools/dob_load_speed_contact_decode.py`，不复用 V1 ABI。

## Simulink 对照设计

160 轮：8 场景 × 10 个固定种子 × V1/V2。两侧均启用原负载降速，唯一策略差异是接触边界保持。
场景为空载、早接触、晚接触、短接触取消、来源缺口、卸载、STOP 和注入故障。
使用保存的原 V1 DLL，与新 V2 DLL 分别通过独立 S-function 模块加载；避免共享静态 DLL loader。
实际消耗的 From Workspace 输入逐点核对，配对噪声和机械参数一致。

机械模型保留原电流 1 ms 一阶近似和 50 µs command delay，不是完整电气 FOC 模型。
短接触取消场景由物理挡块首次接触后独立计时 80 ms 自动解除，时刻不由 DOB 或 FSM 输出产生。
原主机模型还保留其既有 300 rpm 额外 guard，与 MCU 的 500 rpm 正常阈值不同；本轮不修改它，结果不用于验证高转速保护。

验收数据目录：`simulation/dob_simulink/load_speed_contact_results/20261024_203525`。
关闭 Fast Restart，每轮显式重新装载机械参数；植物自身输出实际消费的 J/Kt、B/Kt、库仑项、偏置和电流时间常数。
每轮对照请求参数核验，最终独立审计还逐点比较两侧实际参数、外生输入以及接触保持生效前的全部 64 个原控制输出。

另外发现并复现了仿真编排问题：旧运行使用非可调植物参数配合 Fast Restart，第二个种子请求新参数后，模型仍消费第一个种子的参数。
诊断见 `load_speed_contact_work/restart_parameter_probe.json`：seed2 请求 J/Kt=0.000407973722094567、B/Kt=0.0014824222044296012，
实际仍为 seed1 的 0.000406612182755683／0.0014041172379931053。
此前续跑批次 `20261024_201634` 的接触前输出一致性检查失败，其性能均值不采信，原文件及 `SUPERSEDED.json` 保留。
这个问题不影响已保存的实机数据；旧同类仿真的“机械参数各次随机变化”结论需重新核验，不能仅凭请求参数列证明。

## 最终软件结果

160 轮全部完成。163 项源文件／库哈希检查通过；80 对外生输入、实际机械参数一致，接触保持第一次生效前的原 64 个控制输出逐点一致。
新增阶段保持、取消恢复、原 CONTACT 先后关系、总 Iq／补偿限幅、NEUTRAL、STOP 和故障优先级检查通过。

| 指标（每侧10次，均值±样本标准差） | V1原降速策略 | V2边界保持 |
|---|---:|---:|
| 早接触入口目标错误升速次数 | 10/10 | 0/10 |
| 晚接触入口目标错误升速次数 | 8/8次实际入口 | 0/8次实际入口 |
| 短接触取消场景入口目标错误升速次数 | 10/10 | 0/10 |
| 早接触完成数 | 10/10 | 10/10 |
| 早接触完成时间 | 5.9329±0.22516 s | 5.9329±0.22516 s |
| 早接触 Iq 命令饱和时间 | 223.5±0.527 ms | 222.9±0.568 ms |
| 晚接触完成数 | 5/10 | 5/10 |
| 晚接触完成时间（仅5次成功子集） | 9.6236±0.38414 s | 9.6236±0.38414 s |
| 短接触取消场景 Iq 命令饱和时间 | 54.6±1.265 ms | 52.5±0.850 ms |
| 卸载回到240 rpm±5并连续保持100 ms | 1182.5±37.364 ms | 1182.5±37.364 ms |

主要改善是消除了因状态切换产生的错误目标方向变化；饱和时间变化很小，不能据此宣称真实电机性能显著改善。
取消场景中 V2 的10次候选取消都保留既有目标，而不是立即恢复240；若没有恢复有效分类，200 ms后仍按原失效规则回退。
`contact_metrics.csv` 的 `cancel_events` 专指“取消前调度器仍保留slow状态”的事件，不能把 V1 的0解释为原 FSM 没有取消接触。

严格 jerk 检查仍有30条失败：V1取消场景10次、V1来源缺口10次、V2来源缺口10次。
没有放宽预先固定的1000.2 rpm/s²判据，也没有调整 S 曲线参数；这些失败保留在 `contact_audit.json`。
晚接触两侧均5次未完成，原8秒限时不变，因此本轮只通过接触边界验收，整体自适应策略没有全部通过。
空载、卸载、来源缺口和主动取消挡块场景没有最终工件，保持原rundown超时属于预期过程结果，不冒充完成拧紧。

原始日志160份CSV.gz、`contact_metrics.csv`、`contact_summary.csv`、`contact_pair_audit.csv`、`contact_audit.json` 均在验收目录。
同时归档了两侧DLL、两个SLX、实际参数装载复现、源文件快照和 `artifact_receipt.json`。
曲线为 `contact_early_boundary.png`、`contact_cancel_boundary.png`、`boundary_mean_std.png`。

## 修改文件与复现

固件新增 `firmware_common/load_speed_contact_hold.h`；条件化修改 `dob_load_speed_candidate.h/.c`、A 的 CMakeLists/CMakePresets。
`main.c` 的上轮调用位置不变，原策略 `load_speed_policy.h` 不改，V1 构建选项默认行为不变。

离线新增 `prepare_load_speed_contact.py`、`report_load_speed_contact.py`、V2 解码器、四个 MATLAB 构建/输入/运行/绘图脚本及独立取消接触植物；
`native/load_speed_host.c` 仅在离线 V2 宏下增加保持策略和快照字段。
新增 `load_speed_contact_host.c`、`test_load_speed_contact_hold.py`、`test_load_speed_contact_port.py`、`test_load_speed_contact_report.py`。

复现软件构建：

```text
python tools/prepare_load_speed_contact.py
MATLAB: addpath('D:/new project/simulation/dob_simulink'); run_load_speed_contact('full')
python tools/report_load_speed_contact.py <结果目录>
MATLAB: plot_load_speed_contact('<结果目录>')
python -m unittest discover -s tests -p "test_load_speed*.py" -v
cmake --preset DobLoadSpeedContactHoldCandidate
cmake --build --preset DobLoadSpeedContactHoldCandidate
```

最后两行在 `foc2_app_a` 目录执行。原 `DobLoadSpeedCandidate` 板测镜像和旧结果保留，不覆盖。

## 后续人工板测

先使用新 preset 的精确 BIN/ELF 和 V2 解码，不能直接运行仍固定 V1 哈希的旧刷写脚本。
按既有断电刷非活动 A、完整回读、保留 B、上电校准／时序／栈预检流程准备；本轮尚未执行这些操作。
若预检通过，240 rpm 普通 START、制动器初始释放，在防护外短暂轻制动并解除；不为了触发接触而延长或加重制动。
重点确认进入 CONTACT_CONFIRM 时 selected target 仍为 120、候选取消后不会立即反向提高目标、确认后原 NEUTRAL/IQ 路径接管。
检查实际栈余量、FOC max、deadline miss、CCR late、总 Iq 限幅和原保护；发生保护立即停止，不自动重试。

晚接触超时、卸载恢复较慢和原 S 曲线的严格 jerk 数值边界没有在本次修改中解决，不能宣布整个负载自适应策略已完成验收。
