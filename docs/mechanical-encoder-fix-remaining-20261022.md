# 修复版高转速诊断：补齐原计划剩余八轮

## 计划与身份

用户要求“全部验证完”，本轮补 600 rpm 两次、700 rpm 三次、800 rpm 三次。此前 500 rpm 三次来自修复前高转速 A，600 rpm 一次来自修复版 A；报告必须标注版本差异，不宣称四档均为同固件三次。

仅同一已板测成功的 `MechanicalHighSpeedEncoderFixCandidate`，BIN SHA256 `212ebe9c5c3a8b09a29ed3279ac9c78c100ef80276dfc75de0439c982a7eb862`，ELF `dadb41e4dc5460c70bfce483b777abf7e0d85a4876ee97b059d816d247aac0e3`。

Ka=0.000046875 A/(rpm/s)、BEMF ψ=0.00034866 Wb、摩擦 0.105 A、Iq ±0.50 A、电压 1.60 V，原 PI/S-curve/pipeline/IRQs 保持不变。原已批准超速 1000 rpm、行程 30000°、task 最晚 10.5 秒、独立 lease 12 秒保持；不会重新放宽任何保护。

脚本 `tools/mechanical_encoder_fix_remaining.py` 固定 `[600,600,700,700,700,800,800,800]`，默认仅文件核验；每轮一个 boot / 一次显式 MECH 命令，校准、时序/零速/新 limits 门禁全部保留；独立保护或不能确认关断立即中止，不清除故障、不自动重试。

## 断电准备已完成，尚未运行

用户确认 12 V 仍关闭、MCU 供电、转轴解锁、负载脱开且空载固定/防护/接线未变，机械允许 800 rpm，电源限流 0.5 A、整组现场可立即断电。

原恢复基线 `tmp/mechanical-ident-restore-1792672383329944900.json` 独立核验通过；现有 A 精确相同，因此**不重刷**，只进行两次完整 Flash 回读和停机寄存器核验。

准备 receipt `tmp/mechanical-ident-stage-1792672567432727900.json` PASS：read_only_existing_verified_off=true、independent_readback_pass=true、flash_programming=false、activation=false、motor_commands=0、B/boot/config 未改、输出关闭、CPU halted。

测试 38 项通过：mechanical 系列 34（包含新增只读门禁/身份防篡改四项）、准入修复四项。没有固件改动。

需另行人工确认实际 12 V 开启、无报警、八轮全程在场后才能执行。结束后人工关闭 12 V，再用实际最后 child receipt 恢复原 B 启动选择。DOB 不参与控制，模型结果不自动应用。
