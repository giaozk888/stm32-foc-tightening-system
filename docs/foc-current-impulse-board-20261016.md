# 两拍单点脉冲判别器：2026-10-16 上板记录

## 结论

**已实际进入新版 A，零点通过，三条路径均取得板端计时；整体验收未通过。**
尚未完成预定的30秒稳定运行和应用正常健康确认，不能称为闭环验收通过。

本轮未发送 START，不开启功率桥、不转电机。结束后已恢复原 B 启动选择，
MCU 停在 B 入口，SD/MOE/CCER/TIM1 CEN 均为0。用户已关闭驱动板12 V。

## 镜像与操作范围

- A：`foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin`，225068字节。
- SHA256：`cd2539cad04e76685dd5dcc72b4e82071512b9813ecbd8c1eedffb1c69f5b11e`。
- 运行身份：`FAST_CURRENT_REJECT HARD_OFF=1`，`METHOD=TWO_SAMPLE`。
- 参数保持：JUMP=60、RETURN=25、CONFIRM=25、UNRESOLVED_LIMIT=3。
- 独立保护保持：`FILTER=NONE OC=RAW_2_OF_3 TRIP_MA=4000`。
- 实物状态由用户按阶段确认：刷写时12 V关闭；试运行时开启，
  限流0.5 A，U/V/W动力线断开，IU→PA0、IV→PA1不变。
- 仅改非活动A的擦除页，bootloader、B、私有配置均未变；暂存不改元数据。
- 经原bootloader提交一次试运行；未强制确认、未直接写元数据、未自动重试。

本轮使用 `tools/current_impulse_board_test.py`，绑定本轮SHA与上次恢复的完整
B582基线，复用已有全片比对、擦除页边界检查、bootloader邮箱与恢复流程。
历史脚本中的打印文本仍可能显示旧实验名称/代数；验收身份以精确SHA、
元数据数值、整片比对和本轮运行标识为准，不以旧打印文字为准。
新适配器4项离线测试通过，检查镜像绑定、三路径统计、失败门槛和命令白名单。

## 实测数据

### 零点

`STATE=3 REASON=0 N=4000 U0=1562 V0=1561`，范围U=1552…1572、V=1551…1569。
这是当前校准输出通过；另有未筛选原始零点旁路记录
`RAW_STATE=4 RAW_REASON=2`，不能写成所有原始样本均通过。

### 判别器

| 板端统计 | 数量 |
|---|---:|
| 进入判别器的U/V物理对 | 29503 |
| 接受并进入反馈的对 | 29301 |
| 首次疑似突变 suspect | 200 |
| 算法确认单点脉冲 spike | 190 |
| 确认工作点变化 transition | 9 |
| unresolved累计 | 2 |
| unresolved最大连续 | 1 |
| unresolved后恢复 | 1 |
| 判别器测量故障 | 0 |

共hold 202对（200次首次疑似+2次unresolved）。200次suspect不能称200个物理毛刺；
190次spike是算法分类，未用模拟仪器证实每个点的物理来源。
本次没有出现连续unresolved达到3而故障，但不能据此证明任意工况都无reference锁死。

### DWT路径计时

按170 MHz换算：

| 路径 | 最大cycles | 最大时间 |
|---|---:|---:|
| 正常反馈/FOC计算 | 7110 | 41.82 µs |
| 首次suspect/hold | 4717 | 27.75 µs |
| unresolved/hold | 2524 | 14.85 µs |
| 全路径已观察最大 | 7110 | 41.82 µs |

`deadline_miss=0`。该记录区间内三条路径均低于8500 cycles/50 µs。
这不是30秒通过、全系统WCET证明或真实PWM更新deadline通过。
正常路径统计包含区间内抢占等影响，不能仅凭与旧版19.64 µs的差值
就断言判别核本身增加了22.18 µs，需要分项对照才能归因。

ADC另报 `MISS=0 PF=0 MAX_CYC=6999 LATE=805`；
PWM提交诊断 `BOTTOM_LATE=805 READY=0 HW_VERIFIED=0`，不能隐藏为完全无时序告警。
统计任务栈 `STK_VALID=1 FREE_B=1872`；缓冲区有3次块丢弃、768个样本丢弃，
因此不能声称本轮保存了全部连续原码。

## 为何整体未通过

A尚在启动健康窗口期间进入故障，未完成正常确认。

- 首因：保护链 `REASON=6`，对应 `FOC_FP_TIMEOUT`。
- 不是 `FOC_FP_CURRENT_INVALID=11`（判别器连续unresolved）。
- 故障快照：`FLAGS=0 SEQ=53503 RAW=1564,1566`。
- `LAST_VALID_US=2786645 OFF_US=2786702`；这两个字段相差57 µs，
  **不等于触发超时的内部差值**，不能拿它直接证明100 µs门槛算错。
- `FocFp_Poll`的同一原因码涵盖物理样本新鲜度超时和待确认过流超时；
  当前UART快照未区分具体子条件，根因尚不能只凭原因码确定。
- 没有因失败修改100 µs超时、4 A保护或判别阈值。

下一步如继续诊断，应从本次已保存RAM、对应ELF/布局核验保护结构的
`last_us/pending_us/pending/misses`，并区分两类超时与时间戳顺序；
不要使用旧版硬编码RAM偏移解析新版结构，不需要先重启或再采一次。

## 收尾与证据

收据均位于 `safety_backups/protected-closed-loop-20261014/`：

- `current-impulse-stage-1792152092465389400.json`：暂存及整片比对通过。
- `current-impulse-trial-1792152154565494600.json`：试运行失败，UART和停机RAM已保存。
- `current-impulse-restore-1792152242078681300.json`：恢复原B并停在入口通过。

最终元数据：confirmed=B、pending=none、attempts=0、generation=585。
恢复只改变合法元数据；A/B应用及私有区相对暂存后试运行镜像均未变。
最终完整Flash SHA256：
`26fce0f814b96fa6ff95550a0b15abdc9d5cf785e05e8d1bae479e38ec0fc799`。
完整Flash/RAM位于忽略且受限的private目录，不上传、不在报告中展开。
