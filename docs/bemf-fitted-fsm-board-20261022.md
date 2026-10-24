# 三点磁链候选接入BEMF前馈，空载FSM准备

人工选择上一批三点参考拟合参数，取ψf=0.00069732 Wb。
这是命令电压模型候选，并非已资格化的物理磁链；沿用Rs=0.78 Ω、Ld=20.03 µH假设。
不把单点ψ或两点斜率混入新参数，也不自动把截距0.09009 V当作额外前馈。

## 范围

- A预设 `BemfFittedFluxCandidate` 继承正常 `BemfFeedforwardCandidate`，
  只改变配置中的ψ，开机仍BEMF OFF；无自动START或自动ON。
- 人工上电/预检后，本地输出关闭、空闲状态显式切ON，再执行一次原START。
- 使用原240 rpm/±0.50 A/20000°/8秒rundown、12秒lease的空载FSM。
- 本正常FSM仍使用原300 rpm保护；500 rpm仅前次300/400辨识专用，不继承辨识旁路或API400。
- Vq_ff=有符号实测电角速度[rad/s]*ψ[Wb]；240 rpm/10极对理论约0.17526 V。
- 既有统一矢量限幅、PI-only抗饱和回算、current/speed PI、S-curve、Accel FF、
  摩擦0.105 A、DQ OFF、PWM pipeline和全部其他保护/IRQ均不改。
- 正式B及启动逻辑不改；板测仅非活动A暂存，原bootloader试运行/确认，末尾人工断12 V后恢复B选择。
- 空载应自然RUNDOWN_TIMEOUT，不强制CONTACT，不报告拧紧OK。

13项相关离线测试（原BEMF8项+新候选5项）全部通过。
预处理逐函数证明除了ψ常量，控制/保护/PWM/角度链及正常FSM完全不变。
编译Flash219204 B、静态RAM129560 B；13条既有unused/RWX警告，无新增类别/错误。
BIN SHA256 `6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f`。
ELF SHA256 `a656e26ee84cb1724dcd5033387a3199351fa464b08983d5623559773ef0ceb3`。

主机 `tools/bemf_fitted_fsm_board.py` 默认仅检查文件，显式物理确认才接设备。
复用原单次START/关断/完整Flash+RAM抓取和B恢复流程。
运行时每250 ms查询一次同帧BEMF VOLTAGE，不混合相邻STATUS帧，非全速率极值统计。
收尾核验FF实测公式、关断、原保护/编码器/50us/CCR等；不自动执行OFF对照。

## 刷写前检测到MCU已运行

用户确认12 V关闭、MCU供电、空载固定/解锁、防护和接线不变。
首次 `tmp/bemf-fitted-stage-1792642286019666200.json` 在off_gate返回CPU not halted，
尚未执行Flash写入、复位激活或START。原失败清理路径已关断并halt MCU。
失败保存的完整Flash SHA为 `d3c0808b8a2c44e48e68bc1bc6e1bf432f3788937aef31fe56506fbdb3722bb5`，
逐字节等于上一B940恢复捕获；A、B、boot、metadata及private全部未变。
说明仅停机运行态前提已变化，不是新固件/保护失败；未把旧收据改名伪装。
在输出关闭、CPU已halt及完整身份重新证明后，再进行仅暂存A的准备操作。

## A暂存完成

`tmp/bemf-fitted-stage-1792642353075810400.json` complete/PASS。
仅写A，两次独立完整回读通过，B/boot/private/metadata不变；
activation=false、motor_commands=0、输出关闭、CPU停住，尚未激活或启动。
等待人工12 V上电/无报警确认后，才执行本次BEMF ON试验。

## 本次启动中止：采样零点近0，未执行运动

人工确认上电无报警后，只执行一次候选试运行。
回执 `tmp/bemf-fitted-run-1792642406480673100.json` stopped，
failure=`Probe startup/runtime fault; no retry`。

- `start_attempts=0`，未发送START、没有切BEMF ON。
- `bemf_saved.enabled=0`、valid=0、seq=0，FOC有效控制执行数0、实际CCR提交数0。
  不把本次非控制运行的wall max或零margin当作带电闭环性能。
- first_fault valid=1，domain=STARTUP，保护flags=8（CL_BAD_ZERO）。
- 编码器valid=1，timeout/DMA/schedule/control-stale计数均0。
- 输出关闭、MCU halted，完整Flash/RAM及原B/boot/private保留。

从同次保存RAM、精确ELF符号解码启动校准：

```
cl_zero: size=72（目标ARM枚举为窄枚举，不能按主机enum32布局误读）
state=4 FAILED, reason=2 OUT_OF_RANGE
total=20005, settled=20000, accepted count=0
nominal=1561 ADC counts
observed U range=0..39, V range=0..59
last raw U/V=2/0
cl_zero_filter size=184, robust位于末尾68 B
first collecting block U=[1,0,0,8,2], V=[1,0,0,11,0]
block medians U/V=1/0
robust flags=2 BAD_NOMINAL, total_count=5, reject_count=0
```

这是第一个5对收集窗口的中位数接近0、明显偏离预期1561中点，
**不是累计拒绝过多、CUR_CONFIRM、CURRENT_INVALID、速度环或BEMF前馈失败**。
本次零点offset尚未建立，zero_u/v初始化0不是可采用的校准结果。
软件只证明采样输入几乎为0，不能从此单独证明外部12 V实际电压或哪根线故障；
下一步应核验驱动板VIN、采样放大器供电/输出、公共地及IU/IV接线的实际电压。
不放宽零点名义范围，不用错误零点启动，不自动重试。

人工确认12 V关闭后，仅恢复原B启动选择。
`tmp/bemf-fitted-restore-1792642460402963600.json` complete/PASS，
confirmed B943、pending none、B长度227964/CRC627317606不变。
SD=0、MOE/AOE关闭、CCER=0，CPU停在B入口；B应用未运行，motor_commands=0。
本轮未获得BEMF ON运行效果，不进行虚假的ON/OFF改善比较。

## 人工确认此前未开启12 V后，授权重测一次

人工说明“刚才忘了开启了，现在好了”，随后合并确认实际12 V开启、无报警、
限流0.5 A、空载固定/解锁、防护和接线不变、可立即断电。
没有因此绕过零点检查，也没有提高零点阈值。

板上A已是同一镜像，新增主机只读核验入口 `--verify-existing-powered`：
在已有B943、输出关闭/CPU已halt条件下，只读取两次完整Flash、寄存器和身份。
不写Flash、不reset、不写mailbox、不谎报物理12 V关闭；
独立收据严格校验两次原始文件相同、等于完整恢复基线和当前A镜像。
只读准备回执 `tmp/bemf-fitted-stage-1792642715671075100.json` PASS。
后续执行才按原bootloader试运行流程进行必要复位。

一次运行回执：`tmp/bemf-fitted-run-1792642731451485100.json`。

- 零点恢复正常：valid4000、reject43、total4045、最大连续reject1，U/V=1559/1563。
- 预检通过，恰好1次START，BEMF ON、PSI_NWB=697320、DQ_CROSS=0。
- 原8秒空载FSM自然RUNDOWN_TIMEOUT，CONTACT=0、FLT=0，未伪造拧紧OK。
- 观察到机械转动，STATUS净观察位移10222.18°（约28.4圈），
  运行尾段6个稀疏STATUS均速240.283 rpm；全运行均速包含加速，不与尾段混淆。

| 本次BEMF ON指标 | 实测 |
|---|---:|
| 连续运动建立延迟 | 338 ms |
| 加速MAE | 22.302 rpm |
| 匀速MAE | 4.046 rpm |
| 低速MAE | 12.714 rpm |
| 超调 | 11.381 rpm |
| settling | 7185 ms |
| Iq命令峰值 | 0.479 A |
| Iq测量记录峰值 | 1.387 A |
| speed integrator峰值 | 0.097 A |
| speed PI峰值 | 0.336 A |
| speed Iq限幅饱和时间 | 0 ms |
| FOC wall max | 32.66471 us |
| deadline miss / actual CCR late | 0 / 0 |
| actual CCR min margin | 15.08235 us |
| actual CCR提交 | 299111 |
| CUR_CONFIRM enter/clear/fault | 133/133/0 |

Iq测量峰值包含本系统记录到的测量毛刺，不把它等同于持续物理绕组电流或Iq命令限幅失效。
编码器valid=1，timeout/DMA/schedule/control-stale均0；MOTOR TEST FAULT VALID=0、FLAGS=0。
Flash/RAM捕获SHA复核通过、B/boot/private不变、最终输出关闭且MCU停住。

31个稀疏同帧BEMF查询，29个|omega_e|>=50 rad/s的活动有效帧：
均ON=1、Vq_ff与omega_e*ψ一致，最大整数格式量化差<0.835 uV；
观测|Vq_ff|峰值0.182542 V，活动帧SAT=1次数0。
这不是全速率峰值或全运行电压饱和时间证明，末尾停机RAM帧接近零速也不能替代活动窗口。

### 原始回执STOPPED标签的离线归因

原始回执保持不动：首次主机classify因`first_fault.valid=1`返回STOPPED。
该快照实际为domain=3 PROCESS、fault_reason=3 RUNDOWN_TIMEOUT、timeout_reason=0、
protection_flags=0，正是原FSM `IntentPort_ReportTerminal()` 对空载流程失败写入的快照。
并非硬件/电流/编码器/时序独立保护；原MOTOR TEST FAULT仍valid0/flags0。
只修主机分类，精确允许这一PROCESS超时组合，其余非零保护快照仍拒绝；
新测试覆盖流程超时允许、保护domain/flags/其他timeout不得误允许，共8项新候选测试通过。
用修正后的规则**仅离线重判已保存记录**，未重跑、未修改固件：
acquisition_complete=true，tightening_ok=false。

末尾UART STATUS的UDROP=150（源码定义为丢弃字节数，不是150条样本），
故明确标记full_uart_telemetry_complete=false。
模块RAM/查询聚合N=8000均存在，但不能据此宣称全部tokenized串流完整。
本次没有同批BEMF OFF对照，不能给出因果改善结论；尤其加速误差和超调需关注，
不能仅凭尾段240 rpm及前馈公式正确就宣称控制效果更好。

人工确认12 V关闭后，恢复收据
`tmp/bemf-fitted-restore-1792642797970003500.json` PASS。
输出关闭、CPU停在原B入口，B未执行、motor_commands=0。本轮到此结束。
