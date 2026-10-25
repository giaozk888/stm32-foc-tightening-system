# 第1阶段：只读负载特征与分类

后续修复入口：`run_load_repair('full')`，详见[等级/趋势拆分与短来源缺口说明](LOAD_REPAIR.md)。本文件保留首次阶段设计与运行背景；最新对照保留了旧分类器及旧原始结果，没有覆盖旧证据。

这是 Simulink 软件验证功能，不接入 MCU 固件，不调整速度、电流上限、DOB 补偿增益或 FSM。阶段1 ON/OFF 指“分类旁路启用/关闭”，两侧原有 DOB 估计器均运行、DOB 控制反馈均关闭。不得把它解释成补偿效果对照。

## 运行

```matlab
addpath('D:/new project/simulation/dob_simulink');
run_load_phase1('smoke');  % 开发用小规模检查
run_load_phase1('full');   % 正式：13场景，每组10个种子，两侧成对运行
```

需 MATLAB/Simulink、MSVC MEX 和原项目的 MinGW GCC。`build_load_phase1` 重建现有基础环境并保存 `build/load_phase1/dob_load_phase1.slx`，新增纯 C S-function 输出只连接日志，不连接任何控制执行端。保留原33项输出ABI和原固件文件。

正式种子固定为 1～5、61～65。对于实测回放，前五个仍只选择原始短窗1～3，后五个只选择短窗4～5；没有使用两组结果重新调阈值。13个场景：无载、持续负载阶跃、斜坡、负载卸载、无载单点Id尖峰、持续Id异常、短/长来源缺口、电压饱和质量异常、加强噪声、反向负载，以及实测短窗的测量噪声/真实电流脉冲两种假设。

## 特征与时序

`native/load_features.{h,c}` 是不依赖控制器/观察器/HAL的纯软件消费者；`load_features_sfun.c` 使用独立DWork保存状态，重复的同时间求值使用缓存，Fast Restart恢复冷状态。原观察器继续按既有代码处理电流尖峰和质量；分类器只消费有效、LPF实际更新、来源新鲜且时间戳推进的DOB输出。

- 方向归一化阻力 `direction * disturbance_a`，单位 A等效；原有符号数据另外保留。未知方向或反转先重新确认质量。
- 100ms滑窗，可信样本计算窗口均值和线性回归趋势[A/s]；缺点不插值、不当0。
- 窗口跨度至少60ms、有效覆盖率至少60%；分类候选连续取得30ms有效证据才发布变化。短缺口不提供有效驻留时长，恢复首点不补算缺失时间。
- 首个无效点不更新负载均值、趋势或驻留；保留旧分类记忆但该帧 `label_valid=0`，下游不能把它当作新决策。
- 达20ms没有可信新点，分类层清空自己的特征并转UNKNOWN；它不调用底层DOB Reset。恢复后重新积累窗口与驻留。

软件起始阈值：LIGHT≤10mA，HIGH≥25mA，幅值迟滞5mA；趋势±20mA/s区分RISING/RELEASING，其间为MEDIUM。趋势标签优先于稳态幅值标签，因此真实负载已较高的上升过程仍可能显示RISING。负的助力扰动目前保留有符号特征，分类归入轻载区间，未单设助力类。这些不是实机负载标定值，不是保护阈值。

## 日志与审计

每次仿真生成一个 `.csv.gz`（gzip压缩CSV），含原33项控制/DOB输出、独立负载真值、物理速度/电流、实际测量噪声/输入、实测源窗口，以及：

```text
load_state / load_label_valid / load_mean_a / load_trend_a_s
load_coverage / load_feature_updated / load_reason
load_accepted / load_rejected / load_quality_resets / load_dwell_ms
load_window_good / load_directional_raw_a / load_source_age_ms
load_transitions / load_proposal
```

`load_quality_resets` 统计分类层状态清空，包含STOP、反转和长缺口，不等于底层DOB硬重置；底层真实事件继续看 `epoch_resets/reset_reason`。`load_label_valid=0` 时保留的旧state不能参与新的控制决策。分类器以本次观察时间（现有host控制epoch加20us）与源编码器时间之差计算自己的来源年龄；保留旧33项诊断输出供逐点对照。

结果在独立 `phase1_results/<运行时间>/` 目录：逐次指标、均值/样本标准差、逐对一致性、每场景曲线和运行配置。SDI记录保留在本次独立工作区存储目录，因为当前MATLAB版本禁用记录会让To Workspace返回空日志；运行结束恢复原SDI偏好，不删除旧仿真记录。原始采样长度和时间戳都有强制核验。

对结果运行独立Python审计：

```powershell
python tools/report_dob_load_phase1.py simulation/dob_simulink/phase1_results/<运行时间>
```

审计逐点核对：原控制/观察器/机械真值/输入完全一致、原Iq限幅、NaN/Inf、拒绝点不计有效信用、不污染均值/趋势、不额外累计驻留。软件分类准入预先声明：无载/无载尖峰的轻载误判HIGH不超过1%；有持续负载的正/反向阶跃和卸载场景，HIGH检测在800ms内。任何失败保留，不自动调阈值重新挑结果。

原生回归覆盖正反向幅值、+700mA隔离、短缺口保留、长缺口UNKNOWN及恢复、斜坡与卸载趋势、重复来源、NaN、STOP/FAULT与无效配置；独立审计工具另有故意注入错误的回归。运行：

```powershell
python -m unittest discover -s tests -p test_dob_load_features.py
python -m unittest discover -s tests -p test_dob_load_phase1_report.py
```

真实短窗无法证明其中的电流尖峰到底是测量异常还是真实电流，也没有独立真实负载标签；两种回放假设必须同时报告。合成负载真值由场景源独立生成，不能用DOB输出替代。软件分类通过不等于电机性能或拧紧识别已验证。
