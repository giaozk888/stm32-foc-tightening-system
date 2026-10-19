# −0.10 A / 200 ms 实测与正向对照

## 执行与恢复

2026-10-19，沿用已暂存的同一100 mA诊断A镜像，不刷写、不改固件。现场确认12 V、限流0.5 A、电机空载固定、无报警、可立即断电。新断电检查收据：`tmp/torque100-negative-inspect-1792382087179070800.json`。

本次收据：`tmp/torque100-negative-run-1792382127174402800.json`，同名前缀Flash/RAM均已保存。按正常A/B健康试运行和确认复位完成预检，只发送一次`MOTOR TEST TORQUE NEG ZERO CONFIRM`。IdRef=0，固定IqRef=−0.10 A，绕过速度/位置环输出，电角偏移0。板端实际运行200008 us，未重试，无保护故障；STOP和ANALOG SAFE均收到ACK，随后SWD停机并核验SD/MOE/CCER关闭。

现场随后确认12 V关闭。恢复收据：`tmp/torque100-negative-restore-1792382208312705000.json`，PASS。原B启动选择恢复，generation681、pending0、attempts0；停在B应用入口前，B应用未运行，SD/BDTR/CCER=0，MCU halted。A/B镜像、bootloader、私有配置未变，仅正常启动元数据更新。最终完整Flash SHA256：`9643d9b092bb3a7c2f57bcacea1972ff6cfe4eb10756b19e13fa526fc5ea7334`。

## 校准与时序

- 确认复位后的零点：valid4000、reject40、total4040、max consecutive reject1，zeroU/V=1560/1563，PASS。
- 预检FOC max28.558 us；运行后快照max28.5588 us。
- deadline miss=0，actual CCR late=0，actual commit count129335（包含READY阶段，不是仅200 ms脉冲）。
- 最小actual CCR margin3.6294 us。
- CUR_CONFIRM：61 enter / 61 clear / 0 fault，最多2周期，最大101 us。

## 记录结果

两次均为23个驱动期降采样快照（约8–9 ms间隔），并非连续20 kHz原码；正向来自2026-10-18收据`tmp/torque100-run-1792331835484546300.json`。统计排除停机后terminal帧，位移相对于首个驱动期记录帧，不能覆盖未采样间隙内的全部轨迹。

| 指标 | +0.10 A | −0.10 A |
|---|---:|---:|
| mean Iq (A) | +0.10626 | −0.08907 |
| mean Id (A) | +0.00329 | +0.000575 |
| mean abs(Iq) (A) | 0.10626 | 0.11714 |
| mean abs(Id) (A) | 0.00761 | 0.00846 |
| mean abs(Iq error) (A) | 0.02641 | 0.05773 |
| 净机械位移 (deg) | +0.17578 | −0.57129 |
| 累计绝对位移 (deg) | 0.92285 | 1.45020 |
| 最大正向偏移 (deg) | +0.21973 | 0 |
| 最大负向偏移 (deg) | −0.08789 | −0.65918 |
| 同目标方向/反向/静止区间 | 6 / 5 / 11 | 7 / 4 / 11 |
| Vdq max (V) | 0.06235 | 0.11202 |

本次负向Iq记录范围−0.46976到+0.32280 A，23帧中有1帧Iq反向。95017 us帧：Iq=+0.32280 A、IU/IV raw=1579/1592；157997 us帧：Iq=−0.46976 A、raw=1530/1523。不能仅凭平均Iq接近目标称电流稳定，也不能从这些稀疏帧直接断言是孤立毛刺或连续异常。mean abs(Id)/mean abs(Iq)约7.22%，全部记录无电压饱和、encoder valid。

## 结论与边界

单次负向命令、独立限时停止、时序与保护预检通过；净位移方向与命令符号一致，正负脉冲出现了相反符号的净位移。但负向先移动后停留并有往返，正向也有往返，均不满足“稳定单向运动”。软件平均dq电流和较低Id不能独立证明物理磁链零点、实际相序、电流映射完全正确。

摩擦/齿槽转矩或小电流不足仍是可能原因，尚未排除采样波动、映射和电角对准问题；本轮没有测得实际机械转矩，不能判定根因为摩擦。两次起始电角位置不同，也不能把净位移大小差异直接解释为方向不对称。

没有修改PI、相序、encoder方向、电角零点、Clarke/Park、SVPWM、PWM pipeline、CUR_CONFIRM、current discriminator或任何保护阈值。没有自动提高至0.15 A，没有扫角、没有再次启动。本轮停止在B启动选择恢复、MCU暂停、12 V人工关闭的状态。
