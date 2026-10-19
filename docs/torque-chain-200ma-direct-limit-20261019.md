# 直接Iq限幅改为0.20 A，准备真实正向0.20 A对照

用户在上一轮实际IqRef被0.15 A钳位后，明确要求直接把限幅改为0.2 A。本轮A/B main.c均仅将`MOTOR_DIRECT_IQ_LIMIT_A`由0.15f改为0.20f；真实`MotorControl_SetIq()`和`FOC_EncoderSpeedUpdate()`的IQ分支均复用此宏，因此两处限幅同步。该源码变更适用于后续A/B正式构建，不仅限于诊断；没有改变配方各阶段请求、电流PI、速度PI或4 A故障阈值。已经在板的B回退镜像不改。

使用新的`TorqueChain200mADirectLimitDiagnostic` A/B预设，原被0.15 A截断的200mA、历史50/100mA目录和收据保留，不重标旧数据。仍只允许正向ZERO、IdRef0、单boot一次200 ms手动命令，保留全部健康/校准/超速/过流/超时/数据有效性/PWM保护，不自动运行、不自动重试。

## 回归和构建

新增回归不是旧fake setter：从A/B生产源码提取真实`MotorControl_SetIq`、`ClampFloat`以及真实外环IQ参考赋值，在-O2和-Os下编译执行。请求±0.2、±0.1、±1和0，验证命令与最终IqRef均为预期限幅值；mode切换、预测失效、速度命令清零、取消位置保持一并检查。0.2到达最终参考，1 A仍截为0.2 A。

44项扭矩相关、5项相电流保护、5项原控制配置、3项rundown隔离、30项仿真共87项定向测试通过；未运行本轮全仓库测试，不宣称全部历史测试全绿。

旧隔离测试仅允许一个精确差异：`FOC_EncoderSpeedUpdate`内直接IQ ClampFloat的±0.15f替换为±0.20f，其他冻结体必须完全相同；ADC timing/IRQ对象一致。真实setter另有执行验证。配置显示的DIRECT_IQ_MA测试从150同步200，不改变格式化算法。

旧2倍速度软件仿真原先把“0.15 A模型会OVERTORQUE”作为固定断言；读取新0.2 A后该玩具模型返回MODEL_OK，此为输入限幅变化后的模型行为，不是实机拧紧成功。历史overshoot回归明确固定旧0.15 A fixture，另加新0.2 A仍不能输出硬件质量声明的回归；未改仿真控制器或物理参数掩盖差异。

| 构建 | Flash | RAM (含链接预留) |
|---|---:|---:|
| A200 direct-limit | 229004 B | 130096 B |
| B200 direct-limit | 227980 B | 130080 B |

A BIN SHA256 `3d88bf73e3c8302e88698e52b594850b377671df23179c948583d62c31dafe02`，ELF `c4c250f5307fced92bf773c63598fec056f3e180f6b33c670dfe3bd3a050bc04`。B BIN `37fa12d9b5ec9f83937548bbdf85177449c40e5f6cefcf8c7cee067ccac01420`。A/B编译通过，无新增warning种类（保留历史unused和RWX告警）。没有扩大Flash分区或删除保护。

主机`torque_chain_200ma_acceptance.py`更新为精确绑定新镜像及B685基线：`tmp/torque200-restore-1792382884374099700-flash.bin`，SHA256 `3136f6ee17be34da9546b5450b2212300bfbd3f0795bd94f4b96f6df4d915578`。只有断电暂存和完整回读后才能另行人工上电试运行；同样逐帧要求真实IqRef=0.20 A，不能只凭IQ_MA200状态字称PASS。

预定单次试验为+0.20 A、约200 ms、12 V/限流0.5 A、电机空载固定。目标观察实际电流和运动是否改善，不测量机械扭矩，不仅凭短测自动判定摩擦、相序或电角零点根因。运行/恢复结果后续补记，当前内容不代表已实际执行。

## 实测补记：实际0.20 A参考已验证，未达到稳定持续转动

现场合并确认12V关闭、其余条件不变后，暂存并完整回读A：`tmp/torque200-limit-stage-1792383368418175600.json`，PASS，B685回退与槽外数据未变。随后现场确认开启12V、无报警，只执行一次正向请求。

运行收据：`tmp/torque200-limit-run-1792383430224485000.json`；同名前缀Flash/RAM已保存。通过原健康试运行、确认复位、零点和时序预检；实际驱动200007 us后自动停止，STOP与ANALOG SAFE完成并SWD核验输出关闭、MCU暂停。

**23帧实际IqRef全部为0.20000000298 A**，不再被0.15 A钳位。`pulse_execution_pass`、`timing_pass`、`host_cleanup_pass`均为true；`mechanical_direction_verified`与`torque_accuracy_verified`仍为false，脚本PASS只表示请求幅值/执行/时序/关闭流程通过，不代表稳定转动或扭矩精度合格。

- 正常供电零点：valid4000、reject41、total4045、max连续拒绝1，zeroU/V1559/1563，PASS。
- FOC max28.75294 us，deadline miss0，actual CCR late0，min actual margin2.600 us。
- actual commit count129330包含READY阶段，不是仅脉冲期间的写入次数。
- CUR_CONFIRM51 enter / 51 clear / 0fault，最大2周期、100 us。
- 故障快照valid0，postflight fault/flags0，限时结束后SD/MOE/CCER0。

驱动期仍为约8–9 ms降采样的23帧，不是连续ADC或同步机械测量。以下位移以首个驱动帧为基准，排除停机后的terminal：

| 指标 | 此前+0.10 A | 上轮请求0.20但实际0.15 A | 本次真实+0.20 A参考 |
|---|---:|---:|---:|
| mean Iq (A) | 0.10626 | 0.16778 | 0.20686 |
| mean abs(Id) (A) | 0.00761 | 0.01309 | 0.02648 |
| 净位移 (deg) | +0.17578 | +0.54932 | +1.75781 |
| 累计绝对位移 (deg) | 0.92285 | 1.51611 | 2.94434 |
| 最大正偏移 (deg) | +0.21973 | +0.61523 | +1.91162 |
| 同向/反向/静止区间 | 6/5/11 | 9/6/7 | 9/4/9 |
| sign×净位移/累计路程 | 0.19048 | 0.36232 | 0.59701 |

本次mean Id=+0.00998 A，mean abs(Iq)=0.20686 A，abs(Id)/abs(Iq)约12.80%，Iq平均绝对误差0.05024 A，Vdq最大0.15168 V，无记录到电压饱和或encoder invalid。Iq记录范围0.01886–0.58236 A；61020 us帧Iq0.58236、Id0.23991，因此不能把平均电流接近目标解释成没有波动。单帧不足以认定电流异常的连续长度。

角度序列显示主要运动发生在前约35 ms：首帧机械角−0.04395°，35987 us到+1.86768°，后续多在约1.6–1.8°附近往返，到194951 us为+1.71387°；未形成200 ms内持续单向旋转。210044 us停机后terminal约+0.87891°，不计入驱动位移统计。

增大参考电流后，平均电流与净位移都增大，支持“驱动力大小影响微动响应”；但各次起始转角不同、仅单次短测，不能据此证明唯一根因为摩擦或排除电角对准/相电流物理映射问题。仍不能宣称机械转矩正确或直接进入完整拧紧验收；本轮没有再次加流、负向测试或扫角。

现场确认12V关闭后，恢复原B启动选择：`tmp/torque200-limit-restore-1792383506468509200.json`，PASS。confirmed B、generation689、pending0、attempts0，停在B入口前、B应用未运行，SD/BDTR/CCER=0、MCU halted。B/bootloader/private未变，A保留新诊断镜像；完整Flash SHA256 `bd6f4bde2038b7376585e79ae3f03b0dbcfbeee5d750969847a5fb586bc86268`。没有再启动电机。
