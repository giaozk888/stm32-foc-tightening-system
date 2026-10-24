# 电流PI旁路：固定小电压阶跃诊断候选

## 目的与边界

仅独立A preset `MotorParameterIdentificationVoltageStepDiagnostic`，默认关闭的
`FOC_IDENT_VOLTAGE_STEP_DIAG` 开关控制。不修改正式B、PI参数、相序、电角零点、
PWM pipeline、CUR_CONFIRM、TWO_SAMPLE、IRQ、硬过流/编码器/时序保护。

新镜像的电流PI计算与积分累加在预处理阶段排除，而不是先运行PI再覆盖输出。
速度/位置环仍由原辨识独占模式旁路。正式A/B不开此宏时保留原current PI代码。
原Park、inverse Park、SVPWM、共模分配、pending stage和入口commit沿用现有路径。

命令不兼容旧电流阶跃入口：只接受显式

```
MOTOR TEST IDENT LDV 50MV LOCKED CONFIRM
MOTOR TEST IDENT LQV 50MV LOCKED CONFIRM
```

旧RS/LD/LQ电流命令在此独占镜像不被接受，避免将安培误当伏特。
IdRef/IqRef均为0；50mV是**电压**，不是50mA恒流。

## 波形与固定批次

|阶段|d轴模式|q轴模式|
|---|---|---|
|0–100ms|Vd=Vq=0|Vd=Vq=0|
|100–104ms|Vd=0.050V、Vq=0|Vd=0、Vq=0.050V|
|终止/故障/IDLE/READY|0，原STOP失效pending并关闭门极|相同|

参考owner的固定终止为104ms；原任务后备截止仍是duration+1ms检查，
并有原ADC/encoder/guard故障关断。上表是命令生成的时域规则，不把task调度
或最后一拍PWM保持的误差冒充为示波实测的精确4ms物理脉冲。
禁止自动升压，保留原0.20V诊断退出、速度/非有限量退出和独立保护。
开环电压不再稳住电流，电源限流也不等于相电流限制；锁轴夹具和保护仍必需。

在用户确认全程在场、锁轴/防护、12V/0.5A后，固定运行d/q各3次：
LDV1→LQV1→LDV2→LQV2→LDV3→LQV3。
每段同镜像重新校准/预检、独立one-shot、关断并保存Flash/RAM，段间CPU停住且输出关闭。
质量失败保留并继续预定下一段；真正保护、未知ACK、关断/镜像/传输异常则停整组。
不清故障自动重试，不追加第七段。

## 数据与解释

仍32帧、每帧48B、motor_ident总1740B。为了不扩大RAM，电压专用帧的原
两个参考float槽改为4个uint16：raw_u/raw_v/tail_cnt/tail_flags；因为两个参考本来恒0。
帧另有原us/seq/pending_before、Id/Iq、Vd/Vq、角度/速度、mode/status/reason。
UART明确打印RU/RV/TCNT/TDIR，新policy带`RAW_FRAME_ABI=1`，host使用新BIN/ELF哈希
和`<3I4H6f4B`解码，不拿旧`<3I8f4B`冒充。
TCNT/TDIR是FOC尾部只读位置，不是物理ADC采样孔径或CCR提交位置。

原样本拒绝策略沿用Rs适配诊断：异常dq不进估计，累计/连续数只统计，
可解释hold每次最多2对，不插值、不延长波形；运行时独立CURRENT_INVALID等仍有效。
拒绝统计的first_reject同样使用新的帧ABI，不能解成伪造电流参考。

本实验用于排除PI调节本身的动态：若固定电压下仍有大电流波动，不能再将其
全部归因于PI。新激励与旧50→100mA电流阶跃不是完全等幅的单变量实验，
不能仅比较幅度就认定哪个算法优劣。模拟前端/PWM ripple/死区/实际电压/角度
映射与小电感采样分辨率仍可能影响结果。

Rs=0.78Ω仍仅host临时假设；不自动求得合格电感、不写PI/NVM。原时序/噪声
质量检查保留；不可为让结果出数填写假的latch证据。更不能把50mV命令称为实测相电压。

## 构建与离线

新A：Flash214716 B / 229376 B；RAM130616 B / 131008 B，余392 B，未减少heap/stack。
BIN `e15a2ce8da9ad87752065a40521c4ad55ecfebe4fd9300245060d4499d72228c`。
ELF `bbe64f7fc04a28e51cd8ea2433a148c1d94b8ba16eb98cd4053eb0c77dd306a7`。
B BIN保持 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
构建有既有unused/RWX warnings，不声称零warning。

118项motor-ident相关离线测试通过（非整个仓库测试）：新增波形/退出/命令单位、
PI积分路径排除、其余控制函数冻结、raw ABI识别、未知ACK不重发、批次固定命令等。
日志：`tmp/motor-ident-voltage-build.log`、`tmp/motor-ident-voltage-regression.log`。
脚本：`tools/motor_ident_voltage_batch.py`默认只核验文件，不连接设备。
baseline为原B868停止入口，stage只改非活动A，需上电独立确认后才执行。

## 实测结果：3段完整，第4段独立保护停止

stage `tmp/motor-ident-voltage-stage-1792561351106621100.json`；
batch `tmp/motor-ident-voltage-batch-1792561436183568200.json`。

计划6段：第1段LDV、第2段LQV、第3段LDV均DONE/REASON=0，32帧完整保存。
第4段LQV在启动后约45.050ms、仍是Vd=Vq=0的预备阶段触发独立保护；
尚未到100ms的50mV阶跃，N=0。第5/6段明确NOT_RUN，并非声称全部完成。
3次质量不通过均没有阻止下一预定段；第4次真正保护按约定停止，不清故障重试。

### PI旁路下电流仍有波动

新BIN/ELF、编译展开及wire policy均证明PI_BYPASS=1；每个已存帧与二进制RAM
比对一致，记录Vdq严格只有0或+50mV，另一轴恒0，IdRef/IqRef均0。

|完整段|末12帧轴电流均值 mA|末12帧轴电流标准差 mA|窗口最大相邻变化 mA|seq缺口|
|---|---:|---:|---:|---:|
|LDV1|72.36|10.66|31.74|0|
|LQV1|43.64|51.44|195.85|1|
|LDV2|69.03|13.16|64.86|0|

这些是约1.55ms动态窗口的描述值，末12帧不自动等于稳态；q轴窗口还有缺样。
旧PI电流阶跃的同序号末12帧标准差为13.47、23.16、10.00mA，
新旧激励不同（50→100mA参考 vs 0→50mV电压），不能把标准差差异全部归于PI。

比单纯均值更直接的证据：3段的**零电压预备区**就出现被估计器拒绝的样本。

|段|第一次拒绝相对时间 us|当时记录的前一命令Vd/Vq|测得Id/Iq A|原码U/V|
|---|---:|---|---|---|
|LDV1|1914|0 / 0|+0.0844 / +0.2052|1545 / 1546|
|LQV1|567|0 / 0|−0.2193 / −0.5282|1597 / 1611|
|LDV2|4761|0 / 0|−0.1228 / −0.2689|1581 / 1586|

都是100000us加电压之前。这里是软件换算电流，不是独立电流探头证据。
零dq命令下功率桥仍按原中性PWM开关，因此不能称硬件完全无电压/无共模变化。
可以排除“所有异常都是电流PI振荡”的单一解释，但不能据此排除PI对旧闭环的影响，
也不能未经进一步证据就断言ADC坏、相序错或具体哪个器件出错。
优先检查采样链/零点/共模开关干扰/电压模型；本轮不自动改这些部分。

### 第4段首故障与后续编码器记录要分开

首fault：domain=2、fault_reason=3、timeout_reason=7（FOC_TO_OUTER_CONTROL）、
protection_flags=512（CL_OUTER_STALE）。
`timeout_now_us=8041385`，`reference_us=8039377`，
`elapsed_us=2008 > limit_us=2000`；关断记录`OFF_US=8041389`。
这不是50us FOC deadline，也不是三次CURRENT_INVALID或超速。

事后encoder terminal快照另外有status8、control_stale=1及703us结束记录；
该记录`now_us=8041877`在首fault/关断之后。不能把最终合并flags=544或
encoder_valid=0倒推为编码器事务超时是首因。精确中断PC/调度延迟仍未记录，
本轮只确认外环新鲜度保护先触发，不擅自放宽2000us阈值。

整组4次尝试FOC wall最大36.071us，deadline miss=0，CCR late=0，
最小actual margin15.141us。没有获得合格Ld/Lq，不写PI/NVM。

操作员确认12V关闭后恢复原B启动选择，停在B入口，不运行B应用。
恢复收据 `tmp/motor-ident-voltage-restore-1792561638639795500.json`；
Flash/RAM/原始日志均已保存，无进一步注入。
