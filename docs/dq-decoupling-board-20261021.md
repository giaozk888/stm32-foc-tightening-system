# dq 候选首次人工板测：预检通过，未发送 START

## 实际操作与证据

操作者确认 12 V 关闭、MCU 供电，已解除上一轮锁轴，负载脱开、电机空载固定/有防护，接线不变、电源 12 V/限流 0.5 A、可立即断电。随后按提示上电，并单独确认无报警。

只写非活动 A；双独立完整回读通过，B/boot/config/启动元数据未变，暂存阶段没有激活或启动。随后提交一次正常 A/B 试运行，完成自动健康确认复位与校准/输出关闭时序预检。没有发送 START，没有运行 DQ OFF 运动基线，也没有做 DQ ON 运动对照。

本次旧候选为 `DqDecouplingCandidate`：BIN 218724 B，SHA
`5a37e50da1d6628cc40a0c08eecda21f757310c0c538fb0ae91c22e1e20ed911`。

回执：

- 暂存：`tmp/dq-fsm-stage-1792578487428100000.json`
- 运行/捕获：`tmp/dq-fsm-run-1792578577502929000.json`
- 恢复 B：`tmp/dq-fsm-restore-1792578653224597700.json`

| 项目 | 实测 |
|---|---:|
| 零点 valid/reject/total | 4000 / 47 / 4050 |
| 零点 zero_u / zero_v | 1560 / 1563 |
| 零点 result / reason / flags | PASS / 0 / 0 |
| FOC wall max | 31.2294 µs |
| deadline miss | 0 |
| 实际 CCR commit | 133456 |
| CCR late | 0 |
| 实际最小 margin | 16.6412 µs |
| CUR_CONFIRM enter / clear / fault | 58 / 58 / 0 |
| 首故障快照 valid | 0 |
| START attempts | 0 |

这些是未使能电机运行的累计预检统计，不能冒充运动工况下的 dq 补偿效果。

## 中止原因：诊断回复使用了目标库不支持的浮点格式

上板真实回复：

```text
7800 OK DQ ON=0 VALID=0 SEQ=153148 FRAME_ON=1 OMEGA_E= ID= IQ= LD_UH= LQ_UH=
```

脚本要求明确读回开关/电感，空字段不能当成已确认，所以在 START 前中止。

当前 GCC 链接 `--specs=nano.specs`，没有 `_printf_float` 链接支持。原诊断使用 `snprintf(...,"%.6f",...)`，host GCC 完整 libc 测试可以通过，但目标精简 printf 不能给出这些浮点字段。**这是本次新增诊断接口的目标库兼容缺陷，不是 dq 计算失败、电机保护触发或又一次编码器超时。**

RAM 进一步证实开关写入已经成功：`dq_saved.enabled=0`、`valid=1`、seq=157506，`vd_ff=vq_ff=0`，PI 电压与最终电压相同。切换回复中的 `VALID=0 / FRAME_ON=1` 仅为切换后旧帧失效，不能解释为补偿仍在运行。

中止后调试器确认 SD/MOE/AOE/CCER 关闭、MCU halted。操作者关闭 12 V 后，仅恢复原 B 启动选择并停在 B 入口，B 应用未运行。最终 B 代次 908，pending/active 均 0；B/boot/config/槽外数据保持不变。

## 已完成的离线回复修复（未刷入）

仅修改 `foc_dq_decoupling_binding.inc` 的任务层回复编码，不链接额外浮点 printf 库，不改 dq 公式、PI、保护、频率、pending/CCR 或 IRQ。

- `STATUS`：`OMEGA_E_MRAD_S`、`ID_UA`、`IQ_UA`、`LD_NH=20030`、`LQ_NH=11180`。
- `VOLTAGE`：`VD_PI_UV`、`VQ_PI_UV`、`VD_FF_UV`、`VQ_FF_UV`、`VD_UV`、`VQ_UV`。
- 数值向零截断；不可表示的诊断值用 `INT32_MIN` 哨兵，不参与控制。
- 56 B 原二进制帧及浮点控制计算保持不变。

旧板测 BIN/ELF 和全部回执保留。修正版编译到独立目录：

| 修正版 | FLASH B | RAM B | 结果 |
|---|---:|---:|---|
| A `DqDecouplingWireCandidate` | 219300 | 129600 | PASS |
| A `DqDecouplingWireOffCandidate` | 219300 | 129600 | PASS |

新 ON BIN SHA：`95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`。
ELF SHA：`ed4f4430c57e6b8ba18b81b856a7ac9041a273776da8d9c14b111b9438ef7b45`。

10 项 dq 数学/实际 PI/真实回复/整数格式回归和 4 项板测脚本离线/模拟回归通过；ON/OFF 均未新增警告类别或错误，仍有已有 unused/RWX 警告。不声称修正版已经上板，也不声称整仓库测试全量通过。

板测脚本 `tools/dq_decoupling_fsm_board.py` 已更新为固定新 BIN/ELF/编译标志，基线绑定本次严格恢复的 B908 完整 Flash 和根 B/boot/private 证明；默认仍是 files-only。源码依旧只允许单次原 START、独立人工 ON 运行，无自动重试/强制接触/升流。原阶跃 runner 不用于此镜像。

当前停在：12 V 关闭、原 B 启动选择、MCU 停在入口。修正版等待另一次人工上板重测。

后续人工重测已完成 OFF/ON 各一次，记录见 `docs/dq-decoupling-off-on-board-20261021.md`。本文件保留的是首次未发送 START 的原始经过，不能与后续运动数据混为同一次试运行。
