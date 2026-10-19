# 正向0.20 A / 200 ms对照

> 上板后发现本镜像的0.20 A请求被原直接Iq接口限为0.15 A；**不是有效0.20 A实验**。本页离线准备通过不代表请求幅值到达实际IqRef，详见下文实测补记。本镜像不可再次当作0.20 A已就绪版本。

用户明确要求正向0.2 A实验，观察此前0.1 A断续微动是否与电流太小有关。本轮只新增显式`TorqueChain200mADiagnostic` A/B诊断构建：IdRef=0，固定IqRef=+0.20 A，绕过速度/位置环输出，沿用原电流PI、SVPWM、全部保护和200 ms板端独立停止。每boot最多一次，不自动运行、不自动提高电流；200mA固件解析器和主机只允许POS ZERO CONFIRM，拒绝NEG、扫角、任意幅值和普通START。

正式构建仍默认关闭FOC_TORQUE_CHAIN_DIAG，幅值默认100不变。50/100mA原预设独立保留；重建A/B历史50、100镜像，以及新200共6个构建均通过。实际C准入/任务owner在50/100/200、-O2/-Os运行；200mA负向命令不消耗请求、不使能。只拓展诊断幅值白名单，不修改运行时电流限幅或保护阈值。

200mA与100mA的冻结FOC/保护函数预处理内容相同，ADC timing和IRQ对象一致；未修改PI、相序、encoder方向、电角零点、Clarke/Park、SVPWM、PWM pipeline、CUR_CONFIRM、current discriminator、rundown guard或A/B启动算法。ISR中没有新增记录、格式化或UART。

## 构建与离线检查

| 槽 | Flash | RAM (含链接预留) | 分区Flash剩余 |
|---|---:|---:|---:|
| A200 | 229004 B | 130096 B | 372 B |
| B200 | 227988 B | 130080 B | 1388 B |

A BIN SHA256 `28fc98344577c10cdd01187aeb8386b30304bc08f85edefe0d1d6ac774f66774`；ELF `4e80dc9ccdebee8752c033433e7c930308479252a3e055a21ee7cc122410f607`。

B BIN `d8c5ecc68baf2dfdb8897d2fba4daa0fb37486a92bec3603052b7e980a30a04f`；ELF `dce0fd0f3b831fae529229c8a59370e302986c59a3eaff16a97e312cac98d2dc`。

43项扭矩相关回归及3项rundown隔离测试通过；不是全仓库测试全绿声明。历史50/100mA镜像哈希仍符合原验收脚本固定身份。构建保留既有未使用函数/变量及RWX等warning，无新增warning种类；未删保护或扩大Flash分区。

主机适配器`tools/torque_chain_200ma_acceptance.py`默认只检查文件。精确绑定上述BIN/ELF和原B681完整Flash基线：`tmp/torque100-negative-restore-1792382208312705000-flash.bin`，SHA256 `9643d9b092bb3a7c2f57bcacea1972ff6cfe4eb10756b19e13fa526fc5ea7334`。断电暂存仅写非活动A，完整回读后检查boot/B/private/metadata不变。上电后正常健康确认、零点与时序预检通过才允许一次正向命令；ACK不确定或失败不重试，finally执行原STOP/ANALOG SAFE及SWD捕获关闭。事后需12V关闭再通过原bootloader流程恢复B启动选择、停在B应用前。

解码器支持显式200mA标记，拒绝负200mA、非零角偏移或任意幅值，不把100mA旧数据重标200mA。仍使用约8–9ms间隔的23–25帧窗口和停机terminal，不是连续20kHz原码，PWM applied仍为CCR preload读回。统计mean/absmean Iq/Id、Iq误差、净位移、累计绝对位移、正负最大偏移与方向区间。

## 判读边界

将+0.20 A与此前+0.10 A比较：是否Iq实际增加、运动更连续、净位移相对累计路程的比例提高。若明显改善，支持可用转矩不足的假设，但单次不同起始转角短测不能独立证明摩擦是唯一根因；若仍往返，也不能直接判相序错误。无实际扭矩测量，不验收扭矩精度，不自动改PI、相序或零点。

本文件为准备记录；实际执行和恢复收据应另行补充，不能以离线通过冒充机械运动验收。

## 实测补记：请求被0.15 A接口限幅，验收FAIL

现场确认12V关闭后暂存A，收据`tmp/torque200-stage-1792382715829546100.json`，完整回读通过，B回退及槽外数据未变。随后开启12V、确认无报警，在原健康试运行和自动确认复位后完成预检，发送一次POS命令。

运行收据`tmp/torque200-run-1792382815211725400.json`，对应Flash/RAM均保存。命令与元数据为IQ_MA200、sign+1、offset0，板端限时200008 us后正常关闭，没有保护故障。**23个驱动记录的实际IqRef全部为0.15000000596 A，不是0.20 A**，因此`pulse_execution_pass=false`、整体`pass_=false`；timing和cleanup单项通过。没有修改收据强行标PASS，也没有自动重试。

根因：A main.c的`MOTOR_DIRECT_IQ_LIMIT_A=0.15f`，`LatestOriginal_Admit()`将0.20 A送入`MotorControl_SetIq()`后，被该函数原ClampFloat截为0.15 A。B源代码相同。本轮准备时漏查了实际setter限幅；host准入测试以不含ClampFloat的fake MotorControl_SetIq执行，仅验证命令、状态与保护所有权，未覆盖真实setter幅值钳位。固件上报IQ_MA200是请求配置，不是实际电流参考；主机最终逐帧检查实际IqRef，正确判FAIL。

本次只能保留为0.15 A参考下的观测：平均Iq0.167781 A、平均abs(Id)0.013094 A；净位移+0.549316°、累计绝对位移1.516113°，最大正偏移+0.615234°、负偏移0；9同向/6反向/7静止区间。仍有往返，不是稳定持续正转。Iq记录0.011067至0.582996 A，不能把平均值当作稳定电流，也不能据此认定摩擦是唯一原因。驱动统计仍为降采样快照，排除停机terminal。

预检zero valid4000/reject46/total4050/max连续拒绝1、zeroU/V1560/1563，PASS。FOC max28.723529 us，deadline miss0，CCR late0，min actual margin3.541176 us。CUR_CONFIRM61 enter/61 clear/0fault。未修改保护、PI、相序或电角零点。

现场再次确认12V关闭后，仅通过原bootloader流程恢复B启动选择，收据`tmp/torque200-restore-1792382884374099700.json`，PASS；停在B应用入口前，不执行B应用，SD/MOE/CCER关闭、MCU暂停；A/B应用、bootloader和私有数据保持不变。后续应先修正仅诊断专用的0.20 A请求准入并增加真实setter回归，再另行人工上板；不能直接扩大正式版所有直接Iq限幅，不能把本次数据重标为0.20 A。
