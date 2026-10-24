# DOB 0.25 正常拧紧流程接入

按用户选择，将无量纲 DOB 反馈增益 `0.25` 纳入正常 A 软件预设
`TighteningDob025`。这是正式选用的配置，不是新的参数标定，也不表示
0.25 已被证明优于 OFF；既往空载历史对照未显示明确、稳定的收益，
负载突变抗扰效果仍未验收。

本轮仅修改代码、离线验证与编译：不连接调试器、不刷板、不运行电机、
不替换物理 B。原 B 回退及已冻结的诊断镜像保留。

## 控制行为

```text
iq_dob_target = 0.25 * disturbance_estimate_a
iq_dob_target = clamp(iq_dob_target, +/- min(0.025 A, 0.05 * iq_limit))
iq_raw = iq_pi + iq_acc_ff + iq_friction + iq_dob
iq_ref = clamp(iq_raw, +/- iq_limit)
```

继续使用已经测试的反馈适配器：0.25 A/s 斜率，2 ms 源时间新鲜度，
5 ms 保持、20 ms 前归零；统一总输出限幅与原条件／部分积分 AW。
正常 A 默认选择 DOB ON，但不产生 START，不自动使能功率：仍须原 UART／
RPC START、FSM PRECHECK、功率准入和全部保护通过。

仅速度模式参与补偿，位置／固定 Iq／TIGHTEN／HOLD 不叠加 DOB。
任务在未 armed、非 CL_RUNNING、非 SPEED 或故障时清除补偿；功率关断
仍由原独立 ISR／硬件路径负责，不依赖 DOB 任务执行。
观察器仍须运动建立、原 200 mA pre-LPF 配对筛选、60 mA／20 ms Id
持续质量门控及约398 ms 有效数据预热。异常丢点／长缺口处理不变。

显式进入速度模式时，旧观察器帧、滤波器、计时及统计按 seqlock 原子
发布规则清零，不复用前段估计；反馈默认开启不等于立即有补偿。
`MechanicalDobMonitor_Rearm` 保持 version 在整个清零期间为奇数，避免
whole-struct 赋值短暂把 version 置0而向读任务暴露混合状态。
空闲时原 `MOTOR TEST MECH DOB FB OFF/ON` 开关仍可使用；OFF 不会因模式
重入自动变 ON。MCU 重启恢复所选默认值。

重要：不解除原 ClSession 的每次启动单次准入／一次运行限制，不在 STOP
或故障后自动重试。若重新测试需按原复位、准入流程执行，不能把观察器
可冷启动误读成新增电机自动重启功能。

## 正常流程与保护

预设复用已验证的观察、准入和时间戳实现，但关闭机械辨识运动、FCAL、
高转速诊断、Id trace。因此实际使用 `tightening_intent_binding.inc`，
普通 START 由原 FSM 消费，不需要 `MOTOR TEST MECH RUN`。
保留被动电流发布与 task-after-ACK 观察；不把统计耗时伪装成提前完成。

沿用正常 `TighteningBemfHalfCandidate` 的240 rpm参考／250 rpm速度API、
300 rpm超速保护／20000度行程／12秒总会话限时、原8秒rundown配方。
不把诊断的800 rpm API／1000 rpm trip／30000度行程带入正常流程。
正常速度瞬时合理性门槛仍600 rpm；拒绝帧返回 BUSY 的已有修复保留。
FOC、电流PI、速度PI、S-curve、Ka=`0.000046875 A/(rpm/s)`、摩擦补偿、
BEMF psi=`0.00034866 Wb`、电角零点、相序、IRQ优先级、电流采样、
CUR_CONFIRM、CURRENT_INVALID、一周期PWM pipeline、独立硬过流与
看门狗阈值未修改。

## 修改文件

- `foc2_app_a/CMakeLists.txt`：正常模式开关、依赖／排他检查、显式固定增益。
- `foc2_app_a/CMakePresets.json`：`TighteningDob025` 正常 A 预设。
- `foc2_app_a/Core/Src/main.c`：正常默认ON，保持正常编码器合理性门槛，
  不编译不存在的 FCAL 观察调用。
- `firmware_common/dob_normal_control.h`：task-only 生命周期适配。
- `firmware_common/mechanical_dob_monitor.h/.c`：正常模式专用的 seqlock 重置。
- `firmware_common/dob_feedback_candidate.h`、`dob_feedback_binding.inc`：仅更新
  共享用途注释，不改变适配器计算或参数。
- `firmware_common/protected_closed_loop.inc`：正常 task 生命周期／原诊断协议路由。
- `tests/dob_normal_control_host.c`、`tests/test_dob_normal_control.py`：新增回归。
- `README.md`：将当前正常 A 软件入口指向新预设；历史记录不改写。

所有新行为受 `FOC_DOB_NORMAL_CONTROL` 隔离；旧诊断仍默认OFF及单次生命周期，
原 B 不启用此宏。

## 编译与验证

A `cmake --preset TighteningDob025`、`cmake --build --preset TighteningDob025`
通过：BIN223880 B，链接FLASH223880/229376 B，RAM130768/131008 B，
保留原stack/heap，无新增静态内存扩容。仍有 unused 与 RWX 警告，
不宣称 warning-free；实际任务栈／时序需新组合功率关闭预检。

A BIN SHA256 `0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5`
ELF SHA256 `53642f7a942df34ecb6df41efac7324f22f9534b360c3c0a59df2c500a0adaa7`。
B `MechanicalReviewB` 编译通过，BIN hash 保持
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
review B 构建不等同于板上历史稳定 B 镜像。

新增4项测试通过：真实helper／observer在-Os与-O2下双向0.02A扰动→
0.005A补偿、冷启动预热、尖峰／持续Id、STOP／故障／OFF／重入；
实际预处理代码确认正常FSM与原START准入、正常保护／速度限幅、
默认ON、统一限幅接点；错误增益／诊断owner构建被拒绝；冻结镜像／B
hash未变。当前正常FOC与已板测0.25诊断代码体一致，guard与正常基线一致。
最终181/181项相关回归通过，42个模块各自独立进程执行，记录在
`tmp/dob025-normal-regressions.log`；包含既有各增益／观察器／筛选／
电流／PWM／编码器／准入／时序及新正常模式、FSM／ADC健康回归。
`git diff --check` 对本轮相关已跟踪修改通过。

## 下次人工板测

1. 仍按12V关闭、MCU供电、解锁空载固定有防护的流程；仅更新非活动A，
   完整回读，保留板上B。新镜像hash不同，旧机械RUN脚本不得冒认。
2. 人工上电确认后，先做校准、输出关闭计算／时序／栈预检，确认
   `DOB FB CFG` 的 ON=1、GAIN_PPM=250000，尚无补偿、无自动启动。
3. 用普通 START 执行一次240 rpm空载FSM；检查预热后DOB补偿、
   丢点保持／淡出、总Iq限幅、FOC max、deadline／CCR late及故障。
   空载无CONTACT到RUNDOWN_TIMEOUT不是拧紧OK。
4. STOP核验输出关闭、补偿清零，按原单次准入流程复位后再对照；
   后续固定工件／有防护的受控负载实验另行授权，勿手挡转轴。
5. 不因正常软件构建通过而覆盖B或宣称负载抗扰已通过。
