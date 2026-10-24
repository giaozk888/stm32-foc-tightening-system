# Rs取消累计拒绝退出候选：50mA单次板测

用户分别确认12V OFF、MCU供电、台架锁轴/外壳固定防护/原接线、12V限流0.5A，
授权仅非活动A；完整回读后确认ON无报警、现场可立即断电。
只执行一次RS50，最多400ms；无START、自动重试、升流、Ld/Lq或参数写入。

## 镜像、脚本和回读

- preset `MotorParameterIdentificationRsRejectOnlyDiagnostic`，BIN214628B、ABI1740B。
- BIN SHA256 `c0be6a0d65a1aefa52e30b4b036005ab8787ea96be5f4f720b723f61f820d9d4`。
- ELF SHA256 `c83291d4f565294e30da369a374ceba48bce9c36e04876deae82751331139857`。
- 独立pinned adapter `tools/motor_ident_rs_reject_only_board.py`，精确原B828基线。
- 新3项脚本测试、全部motor-ident相关50项回归通过。
- 旧decoder helper增加显式total_reject_stop可选参数，默认True不改旧行为；
  新runner只在TOTAL_STOP0/REJECT_MAX0/RUN_LIMIT3证据明确时采用无累计退出。
  新候选不能被旧host逻辑按REJECT>16误判失败；但仍需完整有效window与原质量证明。
- stage `tmp/motor-ident-rs50-stage-1792501061318859000.json` PASS，
  完整独立回读、B/boot/private/metadata未变。
- run `tmp/motor-ident-rs50-run-1792501108997244100.json`。

## 结果

校准和时序预检通过，明确ACK，仅1次IdRef50mA/IqRef0。
start_us7982293，last_us8030743，保护关闭时间8030784，约48.5ms停止。

| 项目 | 结果 |
|---|---:|
| 辨识终态 | STATUS4 / REASON1=MID_PROTECTION |
| 原保护标志 | 32=CL_BAD_ENCODER |
| 原first fault valid | 1 |
| Rs有效记录 | N0 |
| current reject / good | 14 / 953 |
| max consecutive reject | 1 |
| total-stop策略 | TOTAL_STOP0 / REJECT_MAX0 / RUN_LIMIT3 |
| Rs gap events / skipped / max | 3 / 3 / 1 |
| timing snapshot valid | 0 |

不是累计拒绝、连续电流拒绝或MID_TIMING退出，而是原编码器保护先关闭输出。
实际累计数仅14，未超过旧16，因此本轮不能实机证明“>16后继续”，
只有离线测试覆盖；本轮能证实新策略日志正确且3次hold缺口接纳。
未到200ms稳态采集窗口，N0，不能计算Rs。

### 编码器故障证据边界

UART `MOTOR TEST FAULT` VALID1/REASON3/FLAGS32/SEQ158249，LAST_VALID_US8030743、OFF_US8030784。
源码 `protected_closed_loop.h` 中32明确为CL_BAD_ENCODER。
保存RAM中 `encoder_timeout_reason=8`，按 `foc_timeout_diag.h` 为
FOC_TO_ENCODER_TRANSACTION；`EncoderDma_FaultFromISR` 将AS_DMA_TIMEOUT映射到此诊断码。
停止后encoder_valid0、foc_fault1、encoder_error_count0。

原首次fault snapshot的timeout_reason=0且encoder_valid1，可能早于该回调后续发布，
不能拿它伪装为完整同周期DMA时长证据。未锁存本次事务pending时间/IRQ硬件状态，
尚不能判断是总线/连线干扰、DMA延迟或调度等具体根因，更不能认定电机抖动引起。
本轮只保留证据，不修改编码器/IRQ/保护时限。

## 电流/时序

首次电流样本拒绝在开始后112us、seq157282，raw1531/1549，
Id0.172477A、Iq0.254868A；|Iq|超诊断0.20A被排除。
此帧不是最终停机原因，也不代表发生4A硬过流。

| 运行时序/保护 | 值 |
|---|---:|
| FOC max | 35.5706us |
| deadline miss | 0 |
| actual CCR commits | 134208 |
| actual CCR late | 0 |
| actual min margin | 15.3294us |
| CUR_CONFIRM enter/clear/fault | 47/47/0 |

## 收尾

先STOP/ANALOG SAFE确认输出关闭，再保存Flash/RAM、halt。
用户确认12V关闭后，原bootloader流程只恢复B启动选择，不执行B应用。
restore `tmp/motor-ident-rs50-restore-1792501184846342900.json` PASS：
confirmed B832、pending0，SD/BDTR/CCER均0，MCU停在B入口，原B/boot/private和A字节保持。
没有后续自动重试或注入。
