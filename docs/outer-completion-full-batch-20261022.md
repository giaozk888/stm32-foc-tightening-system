# 同版本新候选完整重测：500/600/700/800rpm各三次

## 计划与准备

用户要求“完整重测完”，本批不沿用其他固件成绩，固定同一 `MechanicalOuterCompletionCandidate` 依次500×3、600×3、700×3、800×3，共12轮。

- BIN SHA256 `e2f875992a94830d729155137d7aa70fee48feec6f801f61f3788c65db7b0e84`，ELF `6b2ed548cb4751f6dc99b8f16ade53c59667dc0751d576ee7ff06a4348bc6a8f`，与上次600rpm单次成功的镜像相同，固件未改。
- Ka0.000046875 A/(rpm/s)，BEMF有效ψ0.00034866Wb，摩擦0.105A，Iq±0.50A、电压1.60V；超速1000rpm、行程30000°，5秒命令含原S-curve加速、原S-curve减速、task10.5秒关断、独立12秒lease。
- 外环2000µs、编码器确认2500µs、年龄1500µs、事务200µs、IRQ/PI/pipeline/保护保持不变；不启用DOB、不自动应用模型。
- 每轮单次boot/MECH命令，逐轮校准/真实时序/零速/新limits预检，STOP/ANALOG SAFE、完整Flash/RAM/关断与保护核验。独立保护或身份/关断异常停批，不清除故障后重试。质量失败保留数据，不伪造模型合格。
- `tools/outer_completion_full_batch.py` 默认仅文件核验，固定12轮顺序，无新固件烧录路径；复用已测试的read-only OFF完整镜像证明及严格receipt/hash/plan检查，原脚本默认身份不变。
- 43项定向回归通过：outer专项/单次/完整脚本9、mechanical34；固件及其旧158项回归记录不被覆盖或宣称重新全跑。

用户确认12V关闭、MCU供电，机械允许800rpm、转轴解锁/空载固定/防护/接线不变、电源限流0.5A、12轮全程现场可立即断电。

实际上次B恢复基线 `tmp/mechanical-ident-restore-1792673660935323300.json` 已核验。现有A两次完整读回证明receipt：`tmp/mechanical-ident-stage-1792673873164235200.json` PASS；flash_programming=false、activation=false、motor_commands=0，B/boot/config未变，输出关闭、CPU halted。

尚未执行本批12轮，需另行确认实际12V开启、无报警、全程现场后执行。完成/中止后确认关断，人工关闭12V，再用实际最后child receipt仅恢复原B启动选择。

## 实际执行：三轮500完成，600首轮准入拒绝

人工确认上电/无报警/全程现场后执行，批次 `tmp/mechanical-ident-batch-1792673945109935600.json` stopped/PASS=false。

同一新镜像500rpm三轮全部通过安全采集核验；第4轮（首轮600rpm）发送一次显式MECH命令后收到 `7809 ERR MECH NOT_READY`，没有获准运动，不自动重发。该轮停止在启动准入，不是运行到600rpm后的保护故障；700/800未执行。

第4轮 child `tmp/mechanical-ident-run-1792674046856577300.json`：preflight_pass=true，但motion_ack不存在，首故障valid=0，encoder timeout/DMA/schedule/control-stale全0，frozen=0。快照及完整命令窗口均保存。

最后预检 SELFTEST READY=1，MOTOR MODE=IDLE/FLT=0/CTRL=0.1rpm/DET=0rpm，修复limits读回正确；这**不能证明随后命令执行瞬间每个原ProtectedLoop_Ready谓词仍为真**。该谓词还包含PWM-neutral、定时器/功率门极匹配、ADC100µs新鲜度、encoder/会话/控制状态等条件。本固件未在NOT_READY时保存逐谓词失败位，故当前证据不足以指定是哪一个条件失败，不将其臆断为超速、保护过严或上次外环超时。

各轮500rpm FOC max不超过33.577µs、deadline miss=0、CCR late=0，最大任务进入间隔不超过1095µs。三轮数据保留，不把本批报告为12轮完成。

用户确认“关了”后，仅恢复原B启动选择：`tmp/mechanical-ident-restore-1792674199193699400.json` PASS。原B应用227964B/CRC627317606、boot/private/config核验未变；最终VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted、B application not run、motor_commands=0，不再运行电机。

### NOT_READY代码核对（仅离线，不改准入）

机械命令入口在原任务临界区中要求：FCAL未用、CL会话未用且READY、`ProtectedLoop_Ready()`、摩擦ON、控制IDLE、tightening不BUSY、无START/STOP排队，以及SD/MOE/AOE/CCER关闭。

`ProtectedLoop_Ready()`还检查校准/boot确认/UART就绪、原neutral PWM提交资格、ADC/outer计数进展、periodic encoder、CUR_CONFIRM非故障、timer/gates配置、ADC年龄≤100µs、encoder有效且速度≤2rpm等。neutral条件仍为≥1000提交、无late/deadline miss及原pipeline actuation ready。

本次预检与停机后快照表明未锁定故障、encoder正常、neutral/FOC已有大量进展，但均不能回溯命令执行瞬间的每个谓词。当前固件只返回NOT_READY而未保存失败bitmask；**无法从现有数据唯一定位具体条件，不能凭推测解除某项保护或把之前的SELFTEST READY当成永久启动许可**。本轮只核对并记录，不改控制/准入代码、不自动重试。
