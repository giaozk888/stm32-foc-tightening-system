# 编码器准入修复版：一次 600 rpm 人工重测

## 已准备，尚未运动

用户确认 12 V 关闭、MCU 供电、转轴解锁/空载固定/防护/接线未变、12 V 限流 0.5 A、现场可立即断电。仅准备一次 600 rpm，不自动补跑其他档位。

- 新 A 预设 `MechanicalHighSpeedEncoderFixCandidate`，Flash 208524 B、RAM 128776 B，精确镜像见 `encoder-control-stale-admission-fix-20261022.md`。
- `tools/mechanical_encoder_fix_board.py` 默认仅文件检查。先使用旧高转速镜像身份核验实际上次 B 恢复收据 `tmp/mechanical-ident-restore-1792671261759797500.json`，再切换新 A 校验器；不重写或绕过旧镜像身份。
- 启动前强制读回全部高转速 limits，以及 `PLAUSIBLE_RPM=1000 REJECT_BUSY=1`。本次计划严格 `[600]`，仅一次 protected boot / 一次 MECH RUN，无重试、其他速度点、DOB 或自动参数写入。
- Ka=0.000046875 A/(rpm/s)，Iq ±0.50 A、电压 1.60 V、原超速 1000 rpm、行程 30000°、独立 lease 12 秒；5 秒命令阶段及原 S-curve 减速，task 最晚 10.5 秒关断。
- 30 项机械模块/脚本回归与 4 项准入证据/分支复核通过；脚本身份与新 limits 门禁测试包含在 30 项内。
- 暂存 `tmp/mechanical-ident-stage-1792672186454586500.json` PASS：新 A 写入并独立完整回读通过，原 B/boot/private/元数据未变，activation=false、motor_commands=0，输出关闭、CPU halted。

等待另行确认实际 12 V 开启、无报警和现场可立即断电后，才可使用该 stage receipt 执行一次；保护触发即停止，不自动重试。采完先确认输出关断/CPU halt，再人工关闭 12 V，使用实际 child receipt 恢复原 B 选择。

## 一次 600 rpm 实机重测已完成

用户确认实际上电/无报警/可立即断电后执行，没有额外速度点或自动重试。

- 批次 `tmp/mechanical-ident-batch-1792672261219413200.json` PASS；只有一次 child `tmp/mechanical-ident-run-1792672261284359800.json`。
- 新 limits 全部读回通过，包含 `PLAUSIBLE_RPM=1000 REJECT_BUSY=1`。
- 从启动到正常 S-curve 减速关断约 8.03 秒，未触发 10.5 秒 task 强制结束或 12 秒独立 lease。
- FOC max 33.2118 µs，deadline miss=0、CCR late=0；最小实际 CCR 余量 15.0824 µs，actual commit 294644 次。
- 编码器 control_stale / transaction timeout / DMA error / schedule miss 全为 0；同会话 RAM 中 glitch_count=0、glitch_streak=0。
- CUR_CONFIRM 137 enter / 137 clear / 0 fault；板端 MOTOR TEST FAULT VALID=0、FLAGS=0。
- Flash/ELF/BIN/RAM SHA 与原保护/关断资格核验通过；保存 124 个完整 64 ms 窗，capture flags=0。
- 固定稳态分析窗口为 capture 起点 3.65~4.95 秒，共 19 个完整窗：平均速度 598.557 rpm，平均 Iq=0.218231 A，平均绝对 Id=0.037858 A。64 ms 窗端点最大 filtered speed=603.393 rpm，不将它冒充全部原始采样的绝对峰值。

与旧固件在约 580.64 rpm、两次连续合理性拒绝后触发 control-stale 相比，本次通过原故障区域且完成全程，支持本次最小修复有效；单次成功不等于已完成三次重复或 700/800 rpm 验证，也不据此标定 J/B/Kt 或启用 DOB。

用户确认“关了”后，仅恢复原 B 启动选择：`tmp/mechanical-ident-restore-1792672383329944900.json` PASS。

独立核验原 B/boot/private/config 保持不变，B 大小 227964 B、CRC 627317606；最终 VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted，B application not run、motor_commands=0。恢复后不再运行电机，本次单次重测结束。
