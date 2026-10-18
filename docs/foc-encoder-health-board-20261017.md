# 编码器健康检查同步版上板重验

## 结论：启动健康修复通过，完整时序验收未完成

用户确认12 V关闭、其余接线不变后，只写非活动A；完整回读通过，B607回退、bootloader和私有配置保留。用户随后回复开启12 V，按U/V/W动力线断开、IU→PA0／IV→PA1不变的条件，只提交一次功率硬关闭试运行；没有START或功率使能命令。

镜像：`foc2_app_a/build/EncoderHealthReview/EncoderFocFirst/foc2.bin`，228964 bytes，SHA256 `c7eb539311b572e451589ec93b8c8eb4bdddcc4938e3c82c2f0911c45f434408`；匹配ELF SHA256 `03407e5b186b9de756557b5fdcf2b955b9ca71cb0c56ed66e1f7f09443c9caea`。

## 实际取得的证据

- 新A成功进入应用，`MOTOR TEST STATUS`为READY：STATE=1、ZERO=3、FLAGS=0、FAULT=0，SD/MOE/CCER均0。
- `FW STATUS`显示HOK=1、HSTABLE=5000ms、HFAIL=0，日志明确记录 `BOOT HEALTH: PASS 5s` 和正常提交确认后复位。
- 最终完整Flash元数据为 confirmed A、pending none、attempts=0、generation=610。没有强制确认或直接写Flash元数据。
- 说明原 `CL_BAD_TIMER` 优先级预期不一致导致的启动拒绝已消除，但5秒boot health不能代替本轮完整30秒/逐帧deadline与CCR margin验收。

## 未完成的部分与原因

旧试运行脚本在FW查询后立即查询 `MOTOR TEST STATUS`；应用此时恰好自动确认并复位，该只读查询没有ACK，脚本报 `No ACK, never resend: MOTOR TEST STATUS`，按原失败停止策略提前收尾。

停止时CPU已在bootloader（PC=0x080017a6、同停止会话VTOR=0），不是新A应用。没有用A ELF强解此时的SRAM，没有把旧RAM残留当新应用快照，也没有重置/重试取得更好结果。因此本次不报告normal FOC max、TIM2/RX同帧preemption、actual CCR commit/late/min margin等数值；这些仍未完成取证，不能宣称50 µs验收通过。

后续应先让板测脚本的有界启动等待兼容正常健康确认复位：只读查询短时失联后继续等待当前这次确认重启，不重发激活请求、不重发START、不强制确认、不放宽控制/保护阈值。本轮没有因此继续试运行。

## 安全恢复

试运行收尾已锁定SD/PWM并停住MCU，完整应用与私有Flash字节未变。用户确认关闭12 V后，通过正常bootloader请求恢复原B启动选择并停在B入口，恢复通过；不刷B、不启动应用或电机。

恢复辅助仅适配本次已捕获的bootloader owner=0：仍要求CPU已停、SD/MOE/CCER/CEN关闭、完整Flash与停止收据一致、正常元数据恢复、最终B入口断点及字节比较，不能跳过安全门禁。新增离线门禁共5项通过；固件/控制算法没有在本轮进一步修改。

## 收据

- 暂存：`safety_backups/protected-closed-loop-20261014/encoder-health-stage-1792221500954167800.json`。
- 单次试运行（未完整通过）：`safety_backups/protected-closed-loop-20261014/encoder-health-trial-1792221564758231900.json`。
- 恢复B：`safety_backups/protected-closed-loop-20261014/encoder-health-restore-1792221718168887100.json`。

原始Flash/RAM保持在ignored private目录，不公开上传。
