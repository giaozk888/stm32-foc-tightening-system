# 0.20 A直接Iq限幅配置：原完整状态机单次试验

用户要求用当前配置跑完整拧紧流程。当前现场为空载固定，本轮不声称真实工件接触、扭矩精度或拧紧质量验收。只准备从原START入口执行一次完整状态机，已有NO_ROTATION/故障优先停止，不伪造CONTACT/OK，不重复启动。

## 配置

新预设`Rundown200mADirectLimitTrial`继承原`RundownDiagnosticTrial`，显式关闭`FOC_TORQUE_CHAIN_DIAG`。因此不再旁路速度/位置环：原20 rpm RUNDOWN速度控制、接触判据及后续SEATING/TIGHTEN/HOLD配方全部保留。直接Iq限幅±0.20 A是上一轮用户已指定的源码变更；速度环原Iq限幅0.40 A、PI/保护/相序/电角零点均不改。限幅不是实际每阶段电流目标；原配方后续各阶段仍沿用80/100/120/150/150mA等运行时请求，不自动设为200mA。

沿用原12秒板端单boot一次会话租约、主机11.95秒截止、20 rpm临时setpoint并恢复原值，不SAVE、不改持久参数。无法真正起转会NO_ROTATION而非CONTACT；空载不保证能走完所有状态，守卫拒绝继续也必须真实报告。功率关闭时预检通过后才可发送一次START，故障不重试。

## 构建和离线检查

| 构建 | Flash | RAM (含预留) |
|---|---:|---:|
| A | 228220 B | 130080 B |
| B | 227204 B | 130064 B |

A BIN SHA256 `a4848c2e68723a04931ed395bc0a0bf177abf3648db52d484f69756eddf5e96a`；ELF `73866c260a7d7117050a94759b583c7034ee473fec42df90369564f7e54f8146`。B BIN `f7becb511b0b19c6f164155a90e56a584883e993dbd126ba53a456d4c1587e9a`。

A/B编译通过，warning种类与上一轮诊断一致，无新增warning/error。13项该版验收回归通过，涵盖：默认无硬件访问、完整流程不在2秒/CONTACT时提前停止、故障一次START且STOP/SAFE、NO_ROTATION不是电机验收PASS、未arm禁止CONTACT/OK、映像/Flash基线身份、B/private/元数据保留、CLI不允许自动重试/旧prestart resume。冻结FOC计算、encoder更新、PWM pipeline和保护函数与当前0.20 A扭矩诊断版一致；只恢复已有状态机准入所有权与12秒原窗口。未运行全仓库测试，不称全量全绿。

主机适配器`tools/rundown_200ma_acceptance.py`绑定原B689停止基线：`tmp/torque200-limit-restore-1792383506468509200-flash.bin`，完整Flash SHA256 `bd6f4bde2038b7376585e79ae3f03b0dbcfbeee5d750969847a5fb586bc86268`。断电仅暂存非活动A、完整回读；保留B/bootloader/private和正常启动选择。另行人工开启12V/限流0.5 A、确认无报警后才可试运行与START。

复用32帧启动窗口、50ms以上间隔，覆盖前约1.55秒及独立故障/终止帧；主机约50ms STATUS记录全流程，不在ISR格式化或打印。结果必须分开报告状态机流程、实际速度跟踪、NO_ROTATION保护、FOC deadline/CCR late和清理恢复；软件COMPLETE OK不能代替真实转速或扭矩证据。

当前为准备记录，尚不能代表已运行或验收成功。实际收据、故障和恢复结果后续补记。

## 实测补记：RUNDOWN未持续建立，NO_ROTATION停止

现场确认12V关闭、空载固定接线不变后，暂存A并完整回读通过：`tmp/rundown200-stage-1792383787717606700.json`。随后确认12V开启、无报警，沿用0.5 A电源限流，只执行一次原START。

运行收据：`tmp/rundown200-run-1792383851394068100.json`，对应Flash/RAM均保存。先通过健康试运行/自动确认复位、zero valid4000/reject41/total4045/max连续拒绝1、zeroU/V1560/1563和5秒时序预检。主机临时将RUNDOWN_RPM由70设20，不SAVE，结束后恢复70并回读确认。未修改接触、NO_ROTATION、配方电流、PI、相序或零点。

**实际状态仅经过1(RUNDOWN)→11(NO_ROTATION)，没有进入CONTACT/SEATING/TIGHTEN/HOLD，也没有OK。** 板端RUNDOWN elapsed3580 ms停止，主机约3.694 s状态查询确认。过程故障快照domain3/reason7，core_fault=0、保护flags0。脚本总体FAIL是流程/速度未达标，不是主机失联或实时超时；guard_pass=true、no_rotation_protection_verified=true、timing_pass=true、host_cleanup_pass=true，full_state_machine_pass=false、speed_tracking_pass=false。

电机并非完全不动：停止附近机械位置约39.66°，启动目标位置约0.022°，相对位移约39.64°。NO_ROTATION在本工程语义是未持续建立有效RUNDOWN，而不是字面0°。守卫要求现有CTRL与DET同向均达到至少10 rpm、持续100 ms且同一窗口前进至少3°；本次armed一直为0。后续高驱动需求达到原0.30 A条件并持续250 ms，在允许启动时间之后触发既有失败路径。

全程STATUS约50–70 ms查询中CTRL峰值21.0 rpm，15–25 rpm带内最长观测仅约45.8 ms（验收标准需250 ms；不是高频独立转速测量）。记录显示低速爬行、突发运动、速度回落、IqRef重建，不能把短暂21 rpm当作目标速度已稳定建立。

前32个二进制外环快照覆盖约1.57 s，例子：

| 驱动期us | CTRL rpm | DET rpm | IqRef A | Iq A | 机械角deg |
|---:|---:|---:|---:|---:|---:|
| 659930 | 3.954 | 1.077 | +0.283 | +0.257 | 3.142 |
| 710925 | −12.661 | 6.589 | +0.099 | +0.104 | 2.263 |
| 1318928 | 20.176 | 3.807 | −0.039 | +0.012 | 7.361 |
| 1369920 | 12.572 | 18.242 | −0.011 | −0.013 | 10.854 |
| 1420903 | 5.699 | 15.444 | +0.002 | −0.027 | 14.216 |

这些是不同时间基础的外环快照，不是连续ADC或所有通道同刻实测，不能据此直接断言反向制动、电角零点或速度估计某一项就是根因。第一窗口IqRef≥0.20 A的10帧平均IqRef0.24490 A、Iq0.22328 A、Id−0.00834 A，Vdq窗口最大0.16005 V；窗口不能代表完整3.58秒的全程平均。

**本次始终停在SPEED模式RUNDOWN，速度环原Iq上限0.40 A仍生效；新直接Iq限幅±0.20 A没有机会用于后面的直接扭矩阶段。** STATUS临停前IqRef可到375mA是速度环原配置行为，非0.20 A直接Iq限幅失效。故障快照在关闭/清参考后的IqRef=0，不能误读为故障前没有驱动电流。

时序：FOC max28.87059 us、deadline miss0、actual CCR late0、min actual margin5.44118 us，actual commit210149包含READY阶段；CUR_CONFIRM112 enter/112 clear/0fault，最大2周期、101 us。没有证据把本次停止归因于50 us实时性、CUR_CONFIRM或CURRENT_INVALID。

现场确认12V关闭后，只恢复原B启动选择：`tmp/rundown200-restore-1792383946765238700.json`，PASS。confirmed B、generation693、pending0/attempts0，停在B入口前、B应用未运行，SD/BDTR/CCER=0、MCU halted。A保留本次完整状态机镜像，B/bootloader/private未变；完整Flash SHA256 `2d4fb73b4c64c3ba03b9688d3b625f85af28262ed69f9d5a63289578814bfbb4`。只发送一次START，未自动重试。

结论：原完整状态机入口已实测，但没有完成整个流程；假CONTACT修复仍有效，剩余问题是持续起转/速度建立。不能用延长时间或强制CONTACT来声称拧紧成功，下一步需针对断续运动与速度/Iq响应的关联诊断，而不是以本轮时序通过替代转矩链证据。
