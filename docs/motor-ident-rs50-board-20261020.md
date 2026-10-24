# Rs 50 mA 锁转单点准备

用户合并确认：12 V OFF、MCU ON、轴由台架夹具锁定、外壳固定且有防护，
U/V/W 已连接，IU->PA0、IV->PA1、PC6->CTRL_SD 不变，12 V/0.5 A、现场可立即断电。
只授权本轮 Rs 50 mA；不自动进入 75/100 mA 或 Ld/Lq。

`tools/motor_identification_board.py` 固定检查诊断 A BIN/ELF/ABI，复用已验证的
正常 A/B trial/health 自动确认复位/zero/原安全闭合，不提供 START 或任意参考值。
默认只校验文件；4 项 host mock 测试通过（准入、未知 ACK 不重发、先关断再读数据、
无物理确认不访问设备）。不改辨识固件、PI、保护、正常流程或 B。

精确初始 B804 收据：`tmp/friction-fsm-restore-1792494698352284100.json`。
诊断 A BIN SHA `15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d`。
ELF SHA `1e4cf495f8da3ba7dec4c7c211d23ee2c623b7c852a915dd1aa4216cd8909d9f`。

12 V 关闭后只写非活动 A，完整验证并独立回读 PASS：
`tmp/motor-ident-rs50-stage-1792496423708229600.json`。
staged full Flash SHA `310b35be85b813d29204eaed386b16423550d87bde281298217489c733c94d6d`。
B/boot/private/metadata 未变，metadata 仍 B804，无 pending，输出关闭且 CPU 停住。
尚未激活，尚未发辨识命令。

下一步须用户单独确认 12 V ON、0.5 A、无报警且现场可立即断电；随后校准、
正常健康确认复位及输出关闭的 timing/stack 预检全部通过，才单次发送
`MOTOR TEST IDENT RS 50 LOCKED CONFIRM`。板端限时 400 ms；未知 ACK 不重试，
任一保护/诊断包络/时序失败立即停住。先安全关闭输出再读取最多 32 行与 RAM/Flash。
预检失败不注入电流。

## 单次实测结果

用户另行确认 12 V 已开启、无报警、夹具/防护不变、可立即断电，随后只运行一次。
收据：`tmp/motor-ident-rs50-run-1792496491650632600.json`。

- 正常 A/B trial 健康连续 5 秒通过、自动确认复位完成；无强制确认。
- 零点 valid=4000、reject=37、total=4040、zero U/V=1561/1564，PASS。
- MotorControlTask stack VALID=1、FREE_B=2572、6 次观察。
- 预检 FOC wall max=30.747 us、deadline miss=0、actual late=0、margin=15.082 us。
- 仅发一次 `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`，明确 ACK QUEUED。
  `START` 次数 0、excitation_attempts=1，无重试，无后续档位。
- 终态 MODE=1/STATUS=4/REASON=3（MID_CURRENT）、N=0。
  即 `abs(Id)>0.20 A || abs(Iq)>0.20 A` 的新增辨识包络退出，不是原硬过流 latch。
- RAM admission start_us=7977299、原安全停止 cl_stop_us=7977467，约 **168 us**
  后即停止；不是完成了 400 ms。
- 尚未到 200 ms 稳态记录窗口，32 帧数组有效 count=0。
  无 Vd/Id 稳态观测，不能计算单点 Rs，更不能给出拟合 Rs/Ld/Lq。

越界当帧 Id/Iq/raw 未包含在当前只记录稳态窗口的结构中，未得出峰值、哪条轴或
持续时间。停机后的 foc_id/foc_iq 属于后续输出关闭 shadow 计算，不能冒称触发值。
因此不能断言这是实际物理过流或 ADC 毛刺，也不能据此自动放宽包络。
后续若用户要求排查，宜先补诊断 first-abort 前态而不改现有保护或重试升流。

原保护快照 first_fault valid=0；live cl_flags/cl_fault_valid/adc_fault/foc_fault 均0，
encoder_valid=1。CUR_CONFIRM 41 enter /41 clear /0 fault。
本轮 FOC max=34.129412 us、deadline miss=0；actual CCR late=0、min margin=13.947059 us。
UART ADC TIMING 的 LATE 字段是原尾部假设计划统计，不是 actual CCR late；没有混算。
停机 full Flash、RAM 和匹配 ELF 的解码已保存，all_app_private_unchanged=true。

## 断电后恢复

用户确认 12 V 关闭后，仅通过原 bootloader 恢复原 B 启动选择：
`tmp/motor-ident-rs50-restore-1792496559180754300.json` PASS。
SD/MOE/CCER 关闭，MCU 停住，B 应用不运行，恢复过程不发送运动命令。
没有改参数或保护，不继续 Rs75/Rs100/Ld/Lq。
