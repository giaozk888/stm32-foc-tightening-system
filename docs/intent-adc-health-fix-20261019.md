# Intent FSM 首故障映射修复与 ADC 窗口定位

## 完成范围与未解决部分

修复了“底层保护关 session 后，被 task 的 session-loss 检查改报 TIMEOUT”的确定性软件问题。
真实窗口规划失败已离线复现，但**没有删除保护，也没有把真实窗口不足描述为已消除**。
消除该停机需要后续调整 PWM 共模分配/采样兼容策略，或经测量重新核定模拟恢复要求；这超出本次保持 PWM/控制策略不变的范围，本轮未实施。

未使用串口/ST-Link、未刷板/复位/启动/改启动选择；板端继续保持上轮已恢复的 B729、halt、输出关闭，12 V 已由人工关闭。

## 1. TIMEOUT 遮蔽的修复

`firmware_common/tightening_intent_binding.inc::IntentPort_Fault` 原来先执行：

```text
FSM busy && session != RUNNING → TIMEOUT
```

但硬保护先关输出并将 session 标记 FAULT，然后100Hz流程任务才运行，所以真实硬故障也被此分支遮蔽。

现在：

1. 存在底层锁存故障时，先按已有保护 reason/flags 映射。
2. ADC 健康故障单独报告 `ADC_HEALTH`；不伪造 `CURRENT_INVALID`、过流或 timeout。
3. 真正的保护 timeout、compute-late、outer-stale 仍报告 TIMEOUT。
4. **只有没有任何底层故障**、流程仍运行、session意外消失且无人工STOP时，才使用 TIMEOUT fallback。
5. STOP不能抹掉已有故障；任何状态的ADC_HEALTH仍进入 FAULT、意图OFF、禁止OK。

`TF_REASON_ADC_HEALTH` 追加在 enum 末尾，已有reason数值不变；新增可读字符串 `ADC_HEALTH`。
没有重排流程状态、改保护判据、改关桥顺序或新增放行条件。

## 2. RAM / 真实 C 规划器回放

原A728 BIN/ELF及compile_commands在重新编译前保留到本地 `tmp/intent-fsm-a728-evidence/`。
原板测runner继续pin这一份历史证据，不把新ELF错误用于解码旧RAM；它仍pin旧B725 baseline，不是当前B729的新一轮板测入口。

`tools/intent_adc_health_report.py` 只读本地收据、匹配完整Flash、RAM和精确ELF/ABI，不连接硬件。
其默认输入为 `tmp/intent-fsm-run-1792411352445848100.json`。

已确认：

| 项目 | 值 |
|---|---:|
| ADC paired samples | 192214 |
| paired ADC misses | 0 |
| window plan failures | 1 |
| last plan status | 3 = TOO_SHORT |
| 最终保留 duty U/V/W | 0.445023566 / 0.565051556 / 0.434948474 |
| 使用原转换的 CCR U/V/W | 1891 / 2401 / 1848 |
| min low-side observation | 1700 ticks（未改） |
| dead time | 85 ticks（未改） |
| trigger latency / aperture | 14 / 50 ticks（未改） |
| TIM1 ARR / 固定 CCR4 | 4249 / 4184（未改） |

U/V低桥恢复条件要求：

```text
earliest = max(CCR_U, CCR_V) + dead + min_low_on
         = 2401 + 85 + 1700 = 4186

latest = ARR - 1 - latency - aperture
       = 4249 - 1 - 14 - 50 = 4184
```

差2 timer ticks，约0.01176µs；这是几何预算不足，不是FOC计算超过50µs，也不是4A过流。
2 ticks很小不代表可以在没有模拟证据的情况下缩短恢复时间或强行提交无效PWM。

`tests/intent_adc_health_regression.c` 用**现有未经修改**的 `FocAdcWindow_Duty/Plan` 在 `-Os/-O2` 下复现 TOO_SHORT，
并用独立逐tick边沿/恢复时间oracle确认该保留command没有合法触发点。
边界CCR_V=2399时，原算法允许4184且slack=0；2401不允许；neutral仍得到274ticks原余量。
这些边界测试不是将2399写入控制，也不是放宽阈值或截断电压命令。

证据限制：失败计划本身未独立锁存；上述为“原RAM最终保留占空比 + 同次plan_failures=1 + 原C算法复现”，
不能伪称新采集的逐帧失败计划或模拟波形。当前代码将 fixed-trigger mismatch 也归为TOO_SHORT；
此保留command在规划器阶段已经返回TOO_SHORT，独立回放不依赖那个额外mismatch分支。

## 3. 保持不变

- PI、FOC/Clarke/Park、SVPWM数学、限流/限压、相序、电角度、编码器方向。
- CURRENT_INVALID/TWO_SAMPLE、CUR_CONFIRM、稳健零点、NO_ROTATION/motion arm/contact参数。
- one-cycle PWM pipeline、CCR入口提交、采样窗口/恢复时间/触发位置、PWM/ADC频率。
- IRQ优先级、硬过流/encoder/timing保护、A/B启动逻辑。

未新增ISR记录、格式化、统计、浮点或UART负担。修改在100Hz故障原因适配及reason名称；实机时序仍需新候选再测，不能拿旧镜像33.44µs宣称新版已板测。

## 4. 构建与验证

`TighteningIntentCandidate` A/B交叉构建通过，**未替换板上B**。

| build | Flash / 229376B | RAM / 131008B |
|---|---:|---:|
| A | 229252B（余124B） | 128192B |
| B候选 | 228236B | 128176B |

每槽仍为原12条unused及1条RWX警告；无新增警告类别。

- A BIN SHA256: `400739fe8193ce66d1a61b09ab49b14d17d7dfe92693213950669ec6774d94c7`。
- A ELF SHA256: `278d3d05e199c716bf873f9686108f360d18b6cbcb777a51f1580ad4ccbbedb7`。
- B候选BIN SHA256: `d14cb7805552db7144984d938b96fd8fcf388ba56d8d76d12bc6c583aff188ff`。

定向：3项ADC健康/真实故障映射回归、7项FSM回归（追加全状态ADC_HEALTH关闭输出）、4项板测脚本门禁回归、6项现有pipeline回归，全部通过。
本次真实task函数映射回归含：底层ADC健康、CURRENT_INVALID、硬件/确认过流、encoder、overspeed、真正timeout、未解释session loss、人工STOP、PRECHECK/IDLE/运行正常路径。
全仓回归：1383项，432.433秒，18 failure / 4 error；日志 `tmp/intent-adc-all-regression-20261019.log`。
失败/错误用例名称（含subtest）集合与修改前 `tmp/intent-fsm-all-regression-final.log` 完全相同，未新增失败用例名；这不等于全仓通过，也不等于证明每个历史失败内部原因完全相同。
包括旧源码/哈希/镜像基线、本地原始备份依赖、native/Python模拟预期等遗留项；未通过修改保护/PI或删除断言使其变绿。
本次编译警告文本集合与修前相同，`git diff --check`通过。

## 5. 后续所需方向

优先评估在不改变dq电压/相间电压差的前提下，调整三个CCR的**共同偏置**，为当前固定触发位置留出真实恢复窗口。
这会改变PWM共模分配，仍需明确作为独立候选审计、守住占空比/窗口/保护边界，并先离线再功率关闭板测；本轮未加入这一调制策略。
另一方向是测量实际模拟恢复后核定1700ticks配置，不能仅凭外加电容已拆/差2ticks就缩短它。
不能靠改成完整状态机、延长运行、继续升流或清故障来解决此几何不兼容。
解决窗口不足也不等于解决原有断续运动、20rpm跟踪或机械转矩问题；这些必须分别验收。
