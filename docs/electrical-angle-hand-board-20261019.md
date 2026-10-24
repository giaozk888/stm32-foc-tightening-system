# 输出关闭手拧检查：采集丢行，未完成验收

2026-10-19，仅手拧角度链检查；未发 START、固定 Iq 或 offset 命令。功率使能事务在本次手拧镜像中编译禁用。

## 镜像与预检

- 非活动 A：`ElectricalAngleHandDiagnostic`，223380 B。
- BIN SHA-256：`68ef9fdc565476b5da8af0c511e564874d324c7bf4d6c4200bdd2443d86173bf`。
- ELF SHA-256：`2c97a95dcc4d87ff75c58c9f1c91fc83a497bfe94a15a68bf5333c6c20bbba33`。
- 断电暂存、两次完整回读通过：`tmp/angle-hand-stage-1792402521291275700.json`。B709、bootloader、配置与元数据不变。
- 正常 A/B 健康确认复位后为 A712，无强制确认：`tmp/angle-hand-preflight-1792405325329860500.json`。
- 校准 valid=4000、reject=42、total=4045、max consecutive reject=1；zero U/V=1561/1564。
- 预检 FOC wall max=27.535 us、deadline miss=0、actual CCR late=0、actual min margin=16.647 us。
- 手拧前 READY、IDLE、SD=0、MOE=0、CCER=0、FAULT=0；未使能桥。

## 提前结束的原因

原计划 30 秒，但读取 seq=192 时返回 `ERR 109 ANGLE_ROW_MISSING`，不自动重试。
收据：`tmp/angle-hand-hand-1792405388677599100.json`。
文本：`tmp/angle-hand-hand-1792405388677599100.log`。

这是采集器读帧追不上滚动 ring 的问题，不能称为编码器 wrap、相序或 electrical zero 故障：

1. 任务每约 20 ms 生产一帧，ring 仅 12 帧，约 240 ms 留存。
2. 主机串行执行 STATUS/逐行 READ，并额外等待 20 ms；已观察到未读积压逐渐变大。
3. 最后一次 STATUS 的 N=204，而下一待读 seq=192，正好处于最老有效帧边界。
4. 在 READ 被处理之前又写入 seq=204，records=205，最老有效帧变为 seq=193，seq=192 被覆盖。因此前置 `N-next_seq <= 12` 不能保证之后逐条 READ 仍有效。

该链路未测主机请求/响应逐条时间，不把具体延迟武断归咎于 USB、Windows 或某个 ISR。
后续应先修采集吞吐/缓冲留存和边界测试，再人工重新采集；不能跳过缺帧、拼补或用摘要冒充完整窗口。

## 当前能证明的有限结果

- 文本连续保存 seq 0..191，共 192 帧，记录时间约 0..3.958 s；之后有丢帧。
- 整个任务观察在 END 前累计 4245 点，约 4.244 s、205 帧；这不是完整 30 秒手拧验收。
- 任务摘要 errors=0，最大电角比例误差约 0.001831 electrical deg，原机械位置/raw 累计误差=0。
- 摘要最大负机械位移约 -148.10°，尚未完成一整圈并返回。PASS=0 是未满足完整运动窗口，不能据此断言电角链错误。
- 保存的连续文本内，机械角 -132.978° 对应累计电角 -1329.786°；暂未见 10 倍比例或方向异常，但整圈跨界/往返仍未验收。
- 无 first fault；FOC wall max=27.535 us、deadline miss=0、CCR late=0、min actual margin=16.629 us。
- CUR_CONFIRM=319 enter / 319 clear / 0 fault。

即使未来手拧 PASS，也仅证明软件角度符号、解绕与配置的 10 倍比例一致，不能证明实物磁极对数或磁链 d 轴零点。

## 停止与恢复

异常后只发送 STOP/ANALOG SAFE，SWD 停住并保存匹配 Flash/RAM；SD=0、MOE/AOE=0、CCER=0。
用户确认 12 V 关闭后，通过现有 bootloader mailbox 恢复 B 启动选择，在 B 应用入口前停住，未运行 B 应用。
恢复收据：`tmp/angle-hand-restore-1792405482730787000.json`；应用、bootloader 与私有配置字节保持不变。

本轮没有改变控制算法、PI、阈值、相序、编码器方向、electrical zero、PWM pipeline 或正式 B 镜像；未自动补采或启动电机。
