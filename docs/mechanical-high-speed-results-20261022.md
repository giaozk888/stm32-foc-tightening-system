# 500~800 rpm 机械辨识批次：500 三轮完成，600 首轮保护退出

## 实际完成情况

计划及构建：`mechanical-high-speed-plan-20261022.md`。人工确认 12 V 开启、无报警、整组现场后启动。

- 计划 500/600/700/800 rpm 各三次，实际 **500 rpm 三次完成；600 rpm 第一次保护退出；其余八次未运行**。
- 批次 `tmp/mechanical-ident-batch-1792671079944296800.json`，`pass_=false`、phase=stopped；不是完整 12 轮成功。
- 三份正常采集 child receipts：
  - `tmp/mechanical-ident-run-1792671080048255700.json`
  - `tmp/mechanical-ident-run-1792671123251813800.json`
  - `tmp/mechanical-ident-run-1792671152707941600.json`
- 故障 child：`tmp/mechanical-ident-run-1792671182051071100.json`；完整 Flash/RAM/寄存器及编码器故障证据已保存，不删除失败段。
- 未重试、未提高 Iq/电压、未改 PI 或角度链，DOB 未参与控制。
- Ka 始终 `0.000046875 A/(rpm/s)`，有效 BEMF ψ `0.00034866 Wb`、摩擦补偿 0.105 A，Iq ±0.50 A、电压 1.60 V；本诊断超速 1000 rpm、行程 30000°，原 12 秒独立 lease 保留。

## 500 rpm 三轮

稳态统计窗口统一为相对 capture 起点 3.2~4.95 秒，只取完整落入窗口的 64 ms 数据；这是固定时间窗口，不是按残差挑样本。

| 轮次 | 平均实际 rpm | 平均 Iq / A | 平均绝对 Id / A | capture 完整窗 | FOC max / µs |
|---:|---:|---:|---:|---:|---:|
| 1 | 498.853 | 0.200856 | 0.034756 | 116 | 33.294 |
| 2 | 499.718 | 0.200111 | 0.041652 | 117 | 33.265 |
| 3 | 498.748 | 0.203655 | 0.039404 | 114 | 33.229 |

三轮平均实际转速 499.107 rpm，平均 Iq 0.201541 A。各轮同步 capture flags=0、来源核验通过、未到 ring 容量冻结点。

三轮 deadline miss=0、CCR late=0、独立保护=0；CUR_CONFIRM 合计 387 enter / 387 clear / 0 fault。三轮最小实际 CCR 余量 13.306 µs。

## 正向模型：惯量项窗口稳定性改善，但不是绝对参数标定

新增仅文件分析 `tools/mechanical_positive_fit.py`，不改板端采集、准入门限或实际控制。合成模型精确恢复、退化秩拒绝、方向拒绝、无绝对参数/自动写入共三项离线测试通过。

因只有正向，显式合并无法分开的库仑摩擦与电流偏置：

`Iq_lp20 = (J/Kt)*actual_alpha + (B/Kt)*omega + (Tc/Kt + bias)`

使用原同步数据、原固定质量准入和 20 ms 匹配滤波；没有按残差删除样本、变符号、搜索时移或假造反向数据。600 rpm 保护失败段保留，但不作为已通过板端资格核验的模型输入。

可复现结果：`tmp/mechanical-high-500-positive-fit.json`，读取相同 ELF、BIN、Flash、RAM 并逐份复核 SHA/ABI/关断与保护。

| 指标 | 64 ms | 128 ms |
|---|---:|---:|
| 有效窗口 | 300 | 141 |
| J/Kt，A·s²/rad | 0.000334242391 | 0.000355426723 |
| B/Kt，A·s/rad | 0.001736085658 | 0.001747688489 |
| 正向摩擦+偏置等效电流，A | 0.112540104 | 0.112314728 |
| R² | 0.921663 | 0.953719 |
| 残差 RMS，A | 0.007945 | 0.005859 |

J/Kt 的窗口变化为 **6.338%**，三轮逐一留出预测全部通过（残差 RMS 7.53/9.10/7.92 mA），正向比值模型通过既定检查。仅在此限定范围内标记 `normalized_positive_qualified=true`；无独立 Kt，绝对 J/B 仍为 null，无法分别输出 Tc/Kt 与 bias，不自动应用 DOB。

### 与旧数据的比较边界

旧低速正向 100/200/240 rpm 三段用同一三参数正向模型重算，64 ms / 128 ms 的 J/Kt 分别 0.000295602239 / 0.000628668749，且 R² 0.358/0.532、未通过拟合质量。这支持“500 rpm 的更长动态段对本次估计更有帮助”，**不能仅凭本批就证明旧 84% 差异只有加速时间一个原因**。

旧正反向六段与新 500 三段合并的四参数拟合仅是明确标记的跨批次参考：J/Kt=0.000304288099，128 ms=0.000431668018，变化约 41.86%，仍 WINDOW_SENSITIVE；不能把新三轮正向模型的合格替换为完整正反向模型已标定。

## 600 rpm 首轮退出证据

驱动约 3.03 秒时保护退出：

- `FLAGS=32` 对应 `CL_BAD_ENCODER`；编码器 status=8 对应 `AS_DMA_CONTROL_STALE`；`encoder_timeout_reason=10` 对应 control watchdog，而非 SPI transaction timeout。
- filtered speed=580.643 rpm，detect 约 580.0 rpm，trajectory speed command=585.904 rpm；并非达到 1000 rpm 超速阈值。
- IqRef=0.236953 A，Iq=0.263870 A，Id=0.008015 A；Vq_cmd=0.685888 V、Vd_cmd=−0.106795 V，电压未饱和。
- FOC max=33.159 µs，deadline miss=0、CCR late=0；CUR_CONFIRM 70 enter / 70 clear / 0 fault，unresolved 最大连续值 1；不是 CURRENT_INVALID、CUR_CONFIRM 故障或 FOC 耗时超限。
- 编码器 counters：control_stale=1，transaction timeouts=0，DMA errors=0，schedule misses=0。
- RAM 中 `control_due_us=10995976`，故障记录 `now_us=10995977`，晚 1 µs；现有 `AS_DMA_CONTROL_WATCHDOG_US=2500`，说明控制侧确认更新未在原期限内完成。
- 最近成功 DMA sample：sample_us=10995230、completed_us=10995275、elapsed_us=150，早于该事务 200 µs deadline。不能把故障 snapshot 的 started→now=852 µs 误报为 SPI 持续传输了 852 µs。
- 故障 publication 沿用最近成功 sample_us，至故障时间样本年龄约 747 µs，小于原 1500 µs sample-age 阈值；**控制确认看门狗到期和 ADC 使用样本过旧是不同合同**。
- first-fault 的完整 IRQ PC/任务调度历史没有记录；尚不能断定为何控制确认间隔达到 2.5 ms，也不能直接归因于电机转速或串口。末态 UART UDROP=231，仅作并存诊断信息，不当成已证明原因。

本轮只报告保护触发原因与证据，不修改保护、IRQ 或控制任务来自动重试。

后续离线审计已从同份 RAM 发现旧 600 rpm 瞬时合理性门限与 800 rpm 诊断冲突，以及 rejected 样本错误返回 HAL_OK 的假 outer heartbeat。详见 `encoder-control-stale-admission-fix-20261022.md`；这是后续候选修复，不改写本次旧固件板测结果，也不是证明任务饥饿。

## 收尾

故障后 SD=0、MOE/AOE=0、CCER=0、CPU halted。人工确认 12 V 关闭后恢复：`tmp/mechanical-ident-restore-1792671261759797500.json` PASS。

原 B 应用大小 227964 B / CRC 627317606，boot/private/config 核验未变；最终 VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted、B application not run、motor_commands=0。

停止在：三轮 500 rpm 有效数据和 600 rpm 故障证据已保存；原 B 已恢复，不再运行电机。
