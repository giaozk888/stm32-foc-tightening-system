# DOB 负载自适应控制：Simulink 离线验证

**这是软件验证环境，不是电机性能验证。无硬件连接、烧录或电机启动入口。** 原有 A/B 固件源文件和参数不改。先读 [审查和架构](AUDIT_AND_DESIGN.md)。旧 `simulation/tightening` Python 模型不用于本轮结果，避免混入过期参数。

## 运行

本机已检查 MATLAB R2025b、Simulink 许可、MSVC2022 MEX 编译器，以及项目现有 MinGW GCC。`build_dob_simulink.m` 中的 GCC 路径可在移机时调整；运行需要普通 MATLAB+Simulink，不需要 Simscape 或代码生成许可证。原 C 文件由 GCC 编译为仅主机使用的 DLL，C MEX S-function 调用这个 DLL；不是重新写一套 MATLAB DOB。

MATLAB 命令：

```matlab
addpath('D:\new project\simulation\dob_simulink');
run_dob_simulink_suite('full');   % 5 seeds；先 OFF 估计门，再允许 ON 扫描
% run_dob_simulink_suite('smoke'); % 3 seeds、少量场景；不代替 full
```

生成并可打开 `build/dob_offline.slx`。独立构建：`c=build_dob_simulink()`；交互运行模型前用 `storage=dob_storage_session(c)` 将本次 SDI 临时数据设在工作区 D 盘；清除该 cleanup 对象后恢复原存储/记录设置。没有调用 clear/clearPreferences 或降低剩余空间保护。本机最初 C 盘空间不足导致记录关闭，因此不能忽略采样长度断言。

默认总仿真 7 秒，控制 1 ms、plant/命令延迟 50 us。每次运行从冷状态开始；Fast Restart 自定义快照包括 C 全部状态、质量筛选基准、计时器及缓存，参数配置重新应用。MEX/DLL 仅支持**顺序、单实例**；禁止 parsim/多块实例共用该 DLL。修改原 C 后应退出当前运行并在新的 MATLAB 会话重新构建，防止已加载 DLL 被覆盖。

## 阶段门

1. `AUDIT_AND_DESIGN.md`：源代码/单位/符号/更新顺序先审查。
2. 自动编译实际 C、保存 `build/source_manifest.json`；最后核验哈希未变化。
3. 原 C 回归：±扰动、单个 700 mA 尖峰、可信基准恢复、持续 Id、长缺口、复位、STOP、限幅、NaN/Inf 等。
4. OFF 估计门：空载、阶跃、斜坡、卸载、反向；另记录测量噪声、尖峰、持续 Id、短/长来源缺口、电压饱和注入的不可用情况。接受准则在 `dob_config.m` 预先固定；不得根据结果偷偷放宽。
5. 门通过才在**仿真副本**比较 gain=0/.15/.25/.5/1，cap=.0125/.025 A。OFF 共用同场景同 seed，ON 各种配置重复 5 次；限幅不超过原 .025 A 或总 Iq 的 5%，总 Iq 仍 ±.50 A，原 PI/Ka/摩擦/S-curve 不调整。

配置文件分别保存 plant 与 observer 参数：plant 按用户给定 a=.000386049、b=.00155158；observer 直接使用当前 C 的双向联合 a=.00037829065865、b=.00156768643256。Ic=.11945168237 A、bias=.00054966003 A。正向截距 .120735 A 不是独立的 Ic。omega 使用机械 rad/s，负载为有符号 A 等效，不冒充绝对 J/B/Kt 或 N*m。

## 结果

`results/` 每个场景/seed/增益/限幅都有 CSV 和 PNG；保存真实负载、实际机械速度和电流、带噪测量、实际消费的输入、参考/前馈/PI/补偿/限幅、质量原因、LPF 前后、复位和预热。**记录实际入口输入**，不是仅按场景表索引猜测；避免 From Workspace 零阶保持边界造成回放输入偏一拍。

- `native_regressions.json`：原 C 回归。
- `estimator_gate.json`：估计门结果，失败禁止 ON 扫描。
- `metrics_per_trial.csv`：每次试验指标。
- `metrics_mean_std.csv`：场景/增益/限幅分组均值和样本标准差。
- `paired_on_minus_off.csv`：同 seed 的差值均值/标准差及改善/恶化比例；除有效率外数值越低越好。不是不同随机条件的独立均值硬比。
- `replay_check.json`：完整合成记录逐点回放一致性（CSV 浮点容差 1e-6；计数/状态必须严格一致）。失败时保存 `replay_difference.csv`，这不是可以忽略的报警。
- `report.json`：本次种子/运行次数、阶段门、固件哈希检查、限制说明。

用户入口在原始统计后执行 `finalize_dob_results`，将“空载无卸载事件、原始判据已满足等待时间为0”的字段规范为 NaN/N/A，避免误报 0 秒卸载恢复。保留 `metrics_per_trial_raw.csv` 和 `analysis_provenance.json`；该语义归约不修改任何控制器或 plant 行为。单独调用低层 `run_dob_validation` 后也应调用此归约函数再读取最终报告。

完整矩阵结束后可再执行独立文件审计：

```powershell
python simulation/dob_simulink/tools/check_saved_runs.py simulation/dob_simulink/results
```

该工具逐文件核对所有配对的**实际消费输入**哈希，检查 NaN/Inf、独立补偿/总 Iq/积分限幅与隔离点 LPF 不变；输出 `independent_files_audit.json`。`metrics_supplement.csv` 另给出补偿限幅持续时间、plant 实际 Iq 峰值，以及仅显式 WARMUP 状态的累计时间，区别于主表的总 Iq 限幅时间与 Iq 命令峰值。原 C 的 `warmup_s` 实为 `observer.elapsed_s`，有效后仍累加；不能把末值约 6 秒误认为预热花了 6 秒。主表 `warmup_*` 是“观察时钟>0但当前无效”的累计时长，可能包含短缺口；严格预热状态时长以补充表为准。

估计 RMSE/bias/peak 只对评估窗口内有效帧计算，**同时报告整窗口有效率/重置/预热不可用时长**，不把无效帧当真实 0。评估窗口从 2.3 秒到结束前 0.1 秒，启动低速与预热另外由全时域日志保留。检测延迟从真实负载越过半幅到有效估计越过半幅；斜坡不从尚未达到半幅的起点误算延迟。恢复要求连续 100 ms 合格；未恢复记 NaN，不作 0 秒。速度跌落使用机械真值；速度跟踪误差使用原滤波速度；两者不可混淆。

`step` 与 `unload` 使用同一个“突加→保持→卸载”物理协议，分别供事件前半段/后半段查看，不视作两种独立物理证据。

## 回放

完整仿真 CSV 可运行 `dob_replay(path,c)`。真正的高频测量 CSV 可用 `dob_replay_observer(path,c)`，必须提供以下真实字段：

```
observed_us,encoder_us,dt_us,omega_rad_s,id_a,iq_a,adc_seq,
adc_source_us,adc_published_us,current_valid,iq_saturated,current_flags,running,fault
```

它直接重放原 C monitor 的质量检查和观察更新，**不反馈到 Iq**；来源元数据缺失/稀疏点被伪装为连续时拒绝。没有独立负载真值则不计算真实估计 RMSE/检测延迟，不把 DOB 自己作为标签。

历史稀疏 Flash/RAM 记录用只读、无硬件模块的导出器：

```powershell
python simulation/dob_simulink/tools/export_historical_evidence.py `
 --receipt tmp/mechanical-ident-run-1792734456546723200.json `
 --elf foc2_app_a/build/MechanicalDobPreLpf200Candidate/foc2.elf `
 --out simulation/dob_simulink/results/historical --trace
```

先核验原会话 ELF/BIN/Flash/RAM，再输出稀疏 CSV 和明确 `ground_truth_available=false` 的元数据；`dob_plot_historical(folder)` 可画原始 Id/LPF/预热。已验证的 72 点是历史记录，**不是本次新实测**。禁止补点后冒称真实 1 kHz 数据。

## 尚未验证/下一步

- 电流执行器默认 tau=1 ms 是假设，不是新 PI 辨识结果；没有电气 plant、真实 current PI/ADC 噪声闭环、反电动势/电压余量或 FOC 时序模型。速度噪声进入速度反馈，电流异常用于 DOB 专用观测输入，不等于建模了实际电流控制器的噪声响应。
- 50 us Unit Delay 只保留命令延迟，不验证 IRQ、CUR_CONFIRM、CURRENT_INVALID、硬件过流、WCET、CCR late。
- 零速静摩擦平衡是数值模型假设，未验证 stick-slip、柔性传动、螺纹/工件接触、真实负载突变和拧紧质量。没有新增 DOB→CONTACT 状态机逻辑。
- 当前重复性来自固定模型、多噪声种子；不是实际硬件重复性。下一步应做 current tau/机械参数不确定性扫描、再建立更完整电气/柔性模型；有台架后才进行独立测量对照。任何仿真增益优选不自动写回正式固件。
