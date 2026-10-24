# AF1 FF ON：一次空载状态机实测（2026-10-20）

本轮根据人工现场确认：12 V 刷写时关闭、MCU 供电、电机空载固定、接线不变、电源限流0.5 A且可立即断电；只写非活动 A。人工上电后只提交一次正常 A/B 试运行，健康自动确认/复位完成并校准、时序、保护和任务栈预检通过后发送一次原 START。未调参数、未改保护、未重试、未强制 CONTACT。

镜像为 `Tightening240rpmAccelFfOnCandidate`，BIN SHA256 `9a7a0c9d57d8017dea55c31687c3ee2a69dac0d969dbac33a07b70eec0cb2642`；对应 ELF SHA256 `726e57051efdadec67f1cfdf4dbdb99d61e9c743d2fd3927f7c994c9a9890ae9`。新脚本 `tools/accel_ff_fsm_board.py` 独立固定新镜像、B768基线及AF1身份，不修改/绕过旧SC1脚本的校验。11项无设备脚本回归通过，见 `tmp/accel-ff-board-runner-tests.log`。

## 本轮结果

- 240 rpm、Iq限幅±0.50 A、原20000°行程/8秒rundown/12秒板端lease；FF ON，Ka=0.0001875，峰值37.5mA。
- 正常运行8秒，8000个速度更新样本；空载无接触，自然 `RUNDOWN_TIMEOUT`，CONTACT=0，未报告拧紧OK。脚本因此保留 `STOPPED/FAIL`，不是把空载流程误记为成功。
- 最终 `FLT=0`、保护FLAGS=0。首因快照valid=1/domain=3/reason=3为 **PROCESS / RUNDOWN_TIMEOUT**，不是domain=1的电机超速故障；不要仅看reason数字3或valid=1就误判。

| 在线统计 | 实测 |
| --- | ---: |
| 最大 `abs(speed_ref-speed_meas)` | 104.0167 rpm |
| 加速阶段 MAE（约1.399秒） | 25.8567 rpm |
| 参考抵达240rpm后的定向过冲 | 5.9788 rpm，约2.49% |
| 稳定时间 | 未建立（-1，最后一段在带内不足250ms） |
| IqRef峰值 | 0.4180 A |
| 外环采样的Iq反馈峰值 | 1.2785 A |
| 速度积分器峰值 | 0.1623 A |
| 输出饱和累计/最长连续时间 | 0 / 0 ms |
| 减速阶段 MAE | 未测，原STOP不走轨迹减速 |

Iq反馈峰值是软件电流估计在外环采样时读到的峰值，不是平均电流，也未由外部工具证明为真实相电流。峰值明显高于IqRef，不据此宣称电流精度或转矩精度通过。

135个运行中STATUS观察：最高244.8rpm，2～7.9秒99点均值236.316rpm、范围210.6～244.8rpm；尾段7点均值230.443rpm，局部掉速仍在，旧的尾段逐点±10%筛查未通过。这些是稀疏STATUS，不冒充全速峰值；上表来自1kHz在线聚合。

## 时序与日志

- FOC wall max **31.6235us**；50us deadline miss **0**。
- 实际CCR commit **299104**；actual late **0**；最小实际margin **15.1882us**。
- 预检MotorControlTask栈水位FREE_B=2568（6次观察），不是所有任务的完整栈验收。
- 本次零点4000 valid/35 reject/4035 total，最大连续reject=1，zero=1561/1564，PASS。
- 普通token日志206条实际解码、0条解码错误，其中AFF R/C各80条；观察到iq_ff范围0～0.0375A，巡航归零，压缩路径已在实物生效。raw线保持原样，解码单独保存，不覆盖证据。
- UART在运行末端STATUS为UDROP=0，停止后诊断输出突发时UDROP升至166、UERR=0。不能把206条解码全成功等同于“日志无丢失”；本次汇总由板端在线统计和同会话RAM交叉保存，不依赖10Hz日志估峰值。

本轮只有FF ON，没有新镜像相同条件的FF OFF，不能据此证明前馈优于关闭状态。此前旧SC1板测并非同次、同token日志条件对照，不当成严格OFF基线。下一次若人工要求，应先准备独立OFF一次测试收据，再比较相同窗口；本轮没有自动继续。

## 收据及最终状态

- 暂存：`tmp/accel-ff-fsm-stage-1792482977603059700.json`，完整独立回读通过，B/bootloader/配置/元数据未变，尚未激活。
- 运行：`tmp/accel-ff-fsm-run-1792483042168221300.json`，同会话完整Flash/RAM、UART raw/解码、online指标和process快照已保存。
- 恢复：`tmp/accel-ff-fsm-restore-1792483119993591500.json`，PASS。
- 人工已关闭12 V。恢复原已确认 **B772**，pending=0/attempt=0；B镜像和所有槽外配置未变。停在B应用入口，未运行B应用，SD/MOE/CCER全部0，MCU halted。最终Flash SHA256：`413ce5248502cc11d512bf989b4816f5e09c35c7bd850697687115b57d32a358`。

结论：AF1 FF ON的空载运行、合并限幅、日志压缩和时序证据取得；速度仍有局部掉速，稳定性/ON-OFF改进尚未验收，不等同于带工件拧紧或扭矩精度通过。
