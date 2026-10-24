# 加速度前馈隔离对照：人工一次授权的固定六轮

本次不是BEMF ON/OFF比较。BEMF始终OFF，FRIC始终ON/0.105 A，
同一AccelFfAuditGain100诊断镜像上，按百分比0/25/0/50/0/100运行。
0表示Ka=0而Accel框架ON；不把状态字ON=1误解为有加速度补偿。

## 镜像与边界

- BIN 220620 B，SHA256 `0f34df867e0f13ba9e544a89253400936efb4616d33bd2a2027da7731363f6b1`。
- ELF SHA256 `28758a2459e03806f20a718389007be566ebd56051dcac2fa1c54c3f2e384337`。
- 静态RAM130688/131008 B，余320 B；沿用每轮MotorControlTask栈余量至少256 B预检。
- 原确认B951基线：`tmp/bemf-fitted-restore-1792643440402562700.json`。
- 仅12 V关闭时写非活动A，保留原B/boot/private；两次完整回读后再人工上电。
- 240 rpm、Iq±0.50 A、独立300 rpm超速、原8 s rundown/12 s板端lease、20000°行程不改。
- 每轮原START一次、重新校准及预检；不改PI、Scurve、相序、保护、IRQ或PWM pipeline。
- 空载自然RUNDOWN_TIMEOUT只表示观察完成，不是实际拧紧OK；不强制CONTACT。
- 质量差但保护/关断健康的记录保留；真实保护或证据失效立即停整组，不重试不补跑。

## 诊断接口

仅FOC_ACCEL_FF_AUDIT编译可见：`MOTOR TEST FF GAIN 0/25/50/100`。
拒绝其它数值/格式。只有空闲、无启动/停止请求、SD=0/MOE=0/AOE=0/CCER=0才接受。
绝对基准Ka=0.0001875 A/(rpm/s)，不是累计乘增益；只改该诊断参数并清统计，不启桥、不重置PI。
FF和FRIC STATUS都回读实际Ka；全率审计header增加effective_ka，ABI1112 B。
正式A/B没有此命令，正式A BIN仍与原正常镜像逐字节相同。

## 离线检查

4个诊断档与正常A重新编译通过；13条既有unused/RWX警告，无新增。
11项audit/实际C切换安全门/codec/六轮编排测试通过；37项FF/FRIC/AW/Scurve/BEMF既有回归通过。
早期独立测试夹具缺宏的2项编译失败已修复兼容默认，最终37/37通过，不是忽略失败。

## 证据与比较

`tools/accel_ff_gain_batch.py`默认只读文件核验，不访问板端；显式OFF staging、ON supervised batch、OFF restore三个入口。
每轮保存完整Flash/RAM/精确ELF哈希、8000点Task聚合、首1.5秒16帧100 ms间隔审计和20 kHz timing统计。
审计不是500 ms预触发/20 kHz连续波形；不能虚构未记录数据，UDROP按字节报告。
每个非零档只和紧邻前一零档作对比：各非零档n=1，三条零档不等于每个非零档重复三次。
不混合0.25/0.5/1.0成为ON均值，不自动选择或写入最佳Ka，未settle/无减速段为null。

## 实测完成

批次：`tmp/accel-gain-batch-1792645529324602700.json`，6/6采集完成/PASS。
每轮原START一次、8000点速度聚合、8000次轨迹计数；全部BEMF OFF，未烧录其它镜像。
全部空载自然RUNDOWN_TIMEOUT、CONTACT=0/FLT=0，不能报告为真实拧紧完成。

|轮|Ka倍数|起转ms|加速MAE rpm|匀速MAE rpm|超调rpm|Iq命令峰值A|积分器峰值A|settle ms|
|---|---|---|---|---|---|---|---|---|
|1|0|243|16.810|3.611|6.489|0.413|0.079|7267|
|2|0.25|189|10.857|3.635|6.417|0.344|0.086|6521|
|3|0|380|13.499|3.298|6.126|0.415|0.134|未建立|
|4|0.5|419|13.402|3.599|6.155|0.434|0.135|7441|
|5|0|290|13.501|3.690|6.398|0.373|0.119|未建立|
|6|1.0|310|12.080|3.955|6.546|0.353|0.088|7612|

相邻配对结论（不是三次ON平均）：

- 0.25：加速MAE -35.4%，起转延迟 -22.2%，Iq命令峰值0.413→0.344 A，积分峰值稍增。
- 0.5：加速MAE仅-0.7%，起转延迟+10.3%，Iq命令峰值0.415→0.434 A，未显示明确收益。
- 1.0：加速MAE -10.5%，起转延迟+6.9%，匀速误差3.690→3.955 rpm，超调略增；不是全面改善。
- 零档自身起转243..380 ms，加速MAE13.499..16.810 rpm，不能忽略起点/摩擦/零点等轮间变化。
  每个非零档n=1，0.25仅为本次较好候选，不自动写入正式参数，不据此断言全范围最佳Ka。
- 原始“ON恶化”六轮实际切换BEMF，本轮才真正隔离Accel FF；没有复现各档都恶化的结论。

## 公式、时序和AW归因

8000点/轮审计：sign_errors/zero_ff_errors/formula_errors/sync_errors均为0。
accel峰值约200 rpm/s，对应0.25/0.5/1.0前馈峰值9.375/18.750/37.500 mA，
分别为0.50 A Iq limit的1.875%/3.75%/7.5%；无单位或符号错误的直接证据。

所有轮sat_samples/aw_limited_samples/unexpected_aw_samples均为0，饱和时长0 ms。
所以本组不支持“FF使总输出饱和，从而AW误冻结积分器”这一解释。
非零档PI与FF反向样本174/118/338次：在速度超出轨迹或纠偏时可以合理出现，不能单凭符号相反就认定bug。

首500 ms只有6帧100 ms间隔观察：
0.25配对PI绝对值均值91.18→57.75 mA、误差22.79→13.67 rpm；
0.5配对117.14→117.78 mA、27.61→28.08 rpm；
1.0配对110.54→93.51 mA、26.39→24.35 rpm。
这些是稀疏窗口统计，不冒充500点全率均值。无独立减速轨迹段，DEC_MAE均缺失，不填0。

## 实时性与保存证据

- 全组FOC wall最大32.81765 us；deadline miss=0，actual CCR late=0，最小actual margin14.04706 us。
- CUR_CONFIRM累计738 enter/738 clear/0 fault，最大2 cycles；encoder timeout/DMA/schedule/stale均0。
- MotorControlTask预检栈余量2488..2540 B，保留原至少256 B检查。
- 全组UDROP=0 bytes，无token解码错误；二进制RAM/Flash哈希和同镜像校验全部通过。
- 全部原B、boot和private保持不变，未修改PI、保护阈值或正常B算法。

六轮回执依次：
`tmp/accel-gain-run-1792645529398276900.json`、
`tmp/accel-gain-run-1792645574015549500.json`、
`tmp/accel-gain-run-1792645604874765100.json`、
`tmp/accel-gain-run-1792645636276362900.json`、
`tmp/accel-gain-run-1792645667263290400.json`、
`tmp/accel-gain-run-1792645698207257600.json`。

用户确认12 V关闭后，恢复回执`tmp/accel-gain-restore-1792645768217111300.json` PASS。
只恢复原B启动选择并停在B入口，SD/MOE/CCER关闭，B应用未运行、motor_commands=0，不再测试。
