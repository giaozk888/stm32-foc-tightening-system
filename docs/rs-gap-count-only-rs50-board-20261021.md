# Rs可解释间断只计数候选：单次Rs50实测

用户分别确认12V关闭/MCU供电、台架机械锁轴、外壳固定防护、原接线、
12V/0.5A限流及现场立即断电条件。只写非活动A，完整回读后另行确认上电无报警。
恰好执行一次Rs50/最多400ms；无START、无重试、无升档、未进入Ld/Lq。

## 精确镜像及工具

- preset `MotorParameterIdentificationRsGapCountDiagnostic`，BIN215076B。
- BIN SHA256 `68f066ad4fad8df0737271f0b0eec3937266f05ebea253de83f78eea8b212c06`。
- ELF SHA256 `c085819200ad4c7bd345e68b5d0483ed344fccb9cd7674d268dc18f1e9fb3c57`。
- 新runner `tools/motor_ident_rs_gap_count_board.py`，精确B840基线和1740B ABI。
- 3项新脚本检查与全部motor-ident相关合计64项通过。
- host gap decoder的count-only选项显式传递，默认仍按旧16预算；
  不自动重新解释旧会话，也不让L使用Rs间断规则。
- stage `tmp/motor-ident-rs50-stage-1792555672442321300.json` PASS，
  B/boot/private/metadata未变，输出关闭且未激活。
- run `tmp/motor-ident-rs50-run-1792555719749485400.json`。

## 结果：因连续3对辨识电流样本拒绝退出

正常health确认和复位完成，零点、时序、任务栈预检通过。
RS50命令明确ACK；start8018330us，last8166912us，运行148.582ms。
末态MODE1/STATUS4/REASON3，即MID_RS/MID_ABORT/MID_CURRENT。

| 项目 | 结果 |
|---|---:|
| current reject / good | 63 / 2899 |
| 连续reject / 最大连续reject | 3 / 3 |
| current累计退出 | OFF |
| current连续退出上限 | 3（保留） |
| gap events / skipped / max gap | 11 / 11 / 1 |
| gap累计退出 | BUDGET0 / TOTAL_STOP0 |
| gap单次上限 | 2（保留） |
| 首次连续性失败快照valid | 0 |
| 稳态row数 | 0 |

这次不是16次累计gap预算，也不是原63对累计current reject退出。
触发的是保留的连续3对dq envelope（abs(Id)>0.20A或abs(Iq)>0.20A）准入退出。
MID_CURRENT是辨识专用退出，不代表原运行时4A硬过流或CURRENT_INVALID发生。

首次拒绝记录（**不是末尾连续3对故障帧**）：

- 相对起点2316us，seq158047，IU/IV raw1604/1616。
- Id=-0.243099A，Iq=-0.605349A；IdRef=0.05A、IqRef=0。
- 上一计算Vd/Vq约0.020957/0.010195V，非物理相电压计量。

现有ABI仅保存first_reject，不能从该早期帧推断最后3对的逐帧幅值/原码。
不能直接断言这些都是硬件毛刺，也不能证明存在真实持续过流。
若后续定位，应先补足末尾拒绝窗口证据，而不是自动去掉连续异常退出。

记录从200ms才开始，本次在148.582ms退出，因此N0，不能给出Rs或PI建议。
本次只发生11个gap，虽实际策略已读回count-only，但没有实机覆盖>16个gap的情形；
超过16继续工作的验证目前来自离线真实C回放，不夸大为本轮实机已跑完。

## 其他链路

- cl_flags/cl_fault_valid/adc_fault/foc_fault均0；encoder_valid1。
- encoder attempts6702/successes6702/failures0，事务max249us；
  timeout/DMA error/schedule miss/control stale均0，first_fault valid0。
- 成功慢统计前0/后67，包含注入前后命令和停止后读出，不是纯148.582ms窗口计数。
- FOC wall max36.42941us，deadline miss0。
- actual CCR commit136917，late0，min margin14.96471us。
- CUR_CONFIRM74 enter/74 clear/0 fault，max cycles2/elapsed100us。

未修改任何控制算法或保护，未把退出改为成功，未自动重试。

## OFF与B恢复

用户确认12V关闭后，只通过原bootloader流程恢复B，停在入口，未运行B应用。
restore `tmp/motor-ident-rs50-restore-1792555800665025400.json` PASS。
原B应用内容、boot/private及新A字节保持；SD/MOE/CCER关闭、CPU halted。
本轮辨识没有完成，Rs/Ld/Lq均未取得新合格估计值。
