# FR1 摩擦补偿 OFF／ON：一次正向空载对照（2026-10-20）

按人工确认的12V/限流0.5A、空载固定和原接线，分别运行一次FRIC OFF与ON。只在首轮12V关闭时写非活动A并独立回读，第二轮镜像相同，只核验不重复烧写；两轮均先校准、正常健康确认/复位、时序和任务栈预检，再发一次原START。每轮结束由人工关闭12V并恢复原B启动选择。没有自动重试、升流、反转、改PI/阈值或强制CONTACT。

## 对照条件与结果

两轮均使用 `Tightening240rpmFrictionOnCandidate` 同一BIN：`c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8`，匹配ELF：`91a1d63509efefedb2bd89cb0281a65995aac9eaaed64c7964ae2d06c28e306d`。只通过RAM命令切FRIC，启动前再次读回：I_FRIC=0.20A、deadband=2rpm、FF ON/Ka=0.0001875。

目标240rpm、原±0.50A Iq限幅、300rpm独立超速、20000°行程、8秒rundown/12秒板端lease不变。每轮8000个有效速度更新，覆盖约8秒；zero_u/v均1561/1564，MotorControlTask预检栈水位均2572B（6次观察）。两轮空载无接触，最终都是RUNDOWN_TIMEOUT/CONTACT=0/FLT=0，**不是完整拧紧OK**。

| 指标 | FRIC OFF | FRIC ON（0.20A） |
| --- | ---: | ---: |
| 起转延迟，UART整数报告 | 274 ms | 71 ms |
| 低速MAE，2<abs(ref)<=30rpm | 13.077 rpm | 16.889 rpm |
| 匀速MAE | 5.518 rpm | 2.223 rpm |
| speed integrator绝对峰值 | 0.160 A | 0.090 A |
| Iq_PI绝对峰值 | 0.266 A | 0.211 A |
| 总IqRef指令绝对峰值 | 0.304 A | 0.416 A |
| 外环采样Iq反馈绝对峰值 | 1.271 A | 1.252 A |
| 参考抵达240rpm后的定向过冲 | 6.365 rpm | 7.708 rpm |
| 最后建立的稳定时间 | 7.246 s | 1.399 s |
| 输出饱和累计 | 0 ms | 0 ms |
| FOC wall max | 31.671 us | 31.582 us |
| 50us deadline miss | 0 | 0 |
| 实际CCR提交次数 | 298704 | 298504 |
| 实际CCR late | 0 | 0 |
| 实际CCR最小余量 | 13.676 us | 14.435 us |

UART指标取整截断；同会话RAM中的起转延迟分别为274.030ms、71.980ms，四舍五入约274ms/72ms。RAM未取整IqRef峰值为0.304285/0.416569A；积分峰值0.160450/0.090527A；Iq_PI峰值0.266785/0.211167A。

起转判据是同向实测>=2rpm持续50ms，回填该窗口起点；稳定带为±max(2rpm,目标5%)并持续250ms，不是工业速度精度认证。低速窗口仅约0.186/0.187秒，匀速窗口约6.60075秒，比较不能忽略这个覆盖差别。

STATUS稀疏尾段7点均值为OFF237.929、ON240.029rpm，两轮均通过原尾段±10%初筛。这不代替1kHz在线误差；10Hz日志也不足以定位低速误差增大的具体瞬间/机理。暂不把这一结果归因为PI、噪声或特定机械摩擦模型，更未自动调参。

## 如何解读

本次ON起转更快、匀速误差及积分器负担降低，但低速误差更大，Iq指令峰值和过冲更高。**0.20A不是全面改善**，也不是经过标定的摩擦电流。一次OFF/ON受初始转子位置、温度等自然差异影响，不能给出统计普适结论。

只测了正向，NEG样本数两轮均0；比较工具输出NEG与方向不对称为null，正反一致性未验收。未加载工件、未用独立转矩/电流/转速工具，不能证明实际转矩精度。Iq反馈峰值是软件外环采样估计，不是平均电流或独立物理测量；不能说实际相电流始终<=0.50A，0.50A是本轮指令限幅。

两轮process首因快照valid=1/domain=3/reason=3均代表PROCESS/RUNDOWN_TIMEOUT，不是电机超速；保护flags=0，UART MOTOR TEST FAULT VALID=0。脚本保留STOPPED/FAIL是空载流程未成功拧紧，不把实验观察误报成OK。

## 日志、校准和证据

OFF零点4000 valid/54 reject/4055 total，ON4000/32/4035，均PASS；total包含批次已接收但收满valid后未入估计的尾部样本，不等同于valid+reject。原校准实现未修改。

两轮各287条token日志实际解码、解码错误0；FRC记录保留开关及各分量。运行末端UART UDROP=0，停机诊断突发后两轮均升至150、UERR=0，不能宣称无日志丢失。关键指标另存板端在线聚合和同会话完整RAM，不由10Hz日志估峰值。

- 脚本无设备回归14项通过：`tmp/friction-board-runner-tests.log`。
- 首轮暂存：`tmp/friction-fsm-stage-1792486328183965200.json`，真实烧写A并完整独立回读。
- OFF运行：`tmp/friction-fsm-run-1792486530242558900.json`，同会话Flash/RAM、原始UART和解码/指标。
- OFF恢复：`tmp/friction-fsm-restore-1792486601041349100.json`，原B确认generation776，停在入口。
- ON准备：`tmp/friction-fsm-stage-1792486667471447900.json`，`flash_programming=false`、独立回读通过，复用同一A。
- ON运行：`tmp/friction-fsm-run-1792486747099933100.json`。
- 离线对照：`tmp/friction-off-on-comparison.json`，由 `tools/friction_compare.py` 对保存的真实应答生成。
- 最终恢复：`tmp/friction-fsm-restore-1792486818400514000.json`，PASS。

最终人工已关闭12V。原B镜像/bootloader/配置不变，确认generation780、pending=0/attempt=0；停在B应用入口，未运行B应用，SD/MOE/CCER=0、MCU halted。generation是启动元数据计数，不是修改了B固件版本。最终完整Flash SHA256：`23f2ead6a1eee3e98ba8453b613a89a545a9eba3cedd56fb4c4a02b38a4d1d83`。

本轮只新增独立FR1板测脚本/测试和证据文档，不改固件参数或控制算法，不再运行电机。
