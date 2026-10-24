# 固定 ADC 触发点的 PWM 共模分配候选

后续板测更新：已执行一次人工空载状态机实验，结果NO_ROTATION、实际FOC最大31.535µs、CCR late=0；adjusted=0，未覆盖实际平移。见[板测记录](common-mode-fsm-board-20261019.md)。下面保留代码/离线准备阶段的边界与证据。

状态：**仅离线候选，未刷板、未复位、未启动电机、未改启动选择**。
板端仍为上一轮已恢复的原 B729，MCU 停在入口、输出关闭；本轮没有重新测量硬件。

## 改什么、不改什么

新增默认关闭的 `FOC_PWM_COMMON_MODE_ENABLE`，独立 preset `TighteningCommonModeCandidate`，继承 `TighteningIntentCandidate`。
编译约束要求原固定触发 protected pipeline、RC sampling candidate 和 intent FSM；不允许单独将其用于其他 profile。

接入点仅为：

```text
原 FOC / inverse Park / SVPWM duty
  → FocAdcTiming_Prepare
  → FocPwmCommonMode_Plan（新：三相相同整数偏移）
  → 原 FocAdcWindow_Plan（完整重新校验）
  → 原 pending PWM（本拍生成）
  → 下一 ADC IRQ 入口原 commit（CCR1/2/3）
```

不移动 CCR4、不调整 PWM/ADC 频率、不改 latch/update 或一拍延迟，不在计算尾部写真实CCR。
不改 PI、限压/限流、速度/位置环、相序、电角零点、编码器方向、CUR_CONFIRM、TWO_SAMPLE、稳健零点、motion/contact/no-rotation 或硬保护。
纯共模算法只规划，不使能SD/MOE、不写任何寄存器、不申请内存、不做UART/printf。

原SVPWM数学未改，但**PWM零矢量/共模分配策略确实改变了**；不能声称实际开关波形完全不变。

## 分配方法

1. 使用与原 `FocAdcWindow_Duty` 相同的5%～95%输入边界、乘4250及截断方式，得到整数CCR。
2. 根据固定trigger、原dead/settle/RC/latency/aperture约束，计算三相共同允许的最大偏移。
3. 只在需要时对三个CCR施加**同一个非正整数偏移**，取满足本候选约束的最小绝对值；不把每相独立裁剪。
4. 平移后仍必须在原量化占空比范围内。无法容纳则返回 `TOO_SHORT`，不缩小电压矢量、不吞故障、不伪造有效plan。
5. 原窗口规划器必须再次返回OK、trigger仍等于4184，并有额外85ticks窗口slack，才允许生成pending。
6. 原 `PipelinePlanMatches` 和提交permit/保护检查仍执行；planner失败仍走原CL_BAD_ADC关断。

保持的差值是**原限幅/量化后CCR差值**。不是对超过原输入边界的任意浮点电压承诺保持线性。
三线电机无外接中性点时，理想平均相间电压不变；实际共模电压、开关时刻、纹波及EMI可能变化，必须实测。

### 额外余量

`FOC_PWM_COMMON_MODE_RESERVE_TICKS=85U`，170MHz下为0.5µs的**额外数字余量**。
它叠加在原dead=85、settle=85、min_low_on=1700、latency=14、aperture=50上，未缩短原模拟恢复要求。
这是候选初始的可审计数字reserve，不是已测得的模拟噪声消失时间或新保护阈值。
算法在fixed-trigger附近保守要求三相开关边沿均早于采样并保留余量，不为W相另造跨采样窗策略。

## A728 故障command回放

原RAM占空比得到CCR `1891 / 2401 / 1848`，原恢复窗口不足2ticks。
新分配结果：

| 相 | 原量化CCR | 共模候选CCR | 偏移 |
|---|---:|---:|---:|
| U | 1891 | 1804 | -87 |
| V | 2401 | 2314 | -87 |
| W | 1848 | 1761 | -87 |

U−V仍−510，V−W仍553，W−U仍−43。
`2314+85+1700=4099`，到固定4184剩85ticks。
与之相对，neutral `2125/2125/2125` 不平移，保留原274ticks窗口。
无法在5%～95%边界内完成共同平移的command仍拒绝，例如`.95/.05/.5`。
这些只是同一保留command的离线回放，不能证明电机已稳定转动或新版ADC模拟波形已通过。

## 统计及身份

SRAM `foc_pwm_common_mode_diag`（24B）：

- plans、adjusted、rejected；
- last_offset（signed）、max_abs_offset、min_slack_ticks。

只有整数加/compare/assignment，没有新增ISR格式化。统计包含启动与功率关闭shadow planning，**不是实际开桥次数**。
实际CCR commit/late/margin继续使用原独立账本，不混算。
`foc_duty_u/v/w`仍是原SVPWM的**分配前**占空比；不要把它当成平移后的实际CCR。
平移结果应结合signed offset、原pending CCR及真实CCR提交读数解释，CCR读回也不是独立测得的功率桥波形。
`MOTOR TEST PROFILE` 在本候选附加 `CM=85`，表示共模分配启用及reserve为85timer ticks；完整profile仍能放入原192B buffer，末尾QUALIFIED=0不丢失。

没有新增自动启动命令、自动扫点、自动升流、保护清除或运行时开关。

## Flash与栈约束

初次A链接超出452B。为容纳候选，只对该profile的冷格式化路径做尺寸优化：

- `TighteningResult_PrintStage`、`TighteningResult_PrintSummary`、`Protocol_PrintStatus`、`FocAdcTiming_Format` 使用`-Oz`函数属性；
- `FocStartup_Scaled` 原重复内联转换改为共享的cold `noinline/-Oz`函数；数值转换、NaN/范围哨兵及trace字段保持原样。
- 不删协议字段、trace窗口、日志/保护功能，不对PI/FOC/ISR整体启用`-Oz`或fast-math。

| build | Flash / 229376B | RAM / 131008B |
|---|---:|---:|
| Common-mode A | 229308B（余68B） | 128808B（余2200B） |
| Common-mode B交叉构建 | 228300B | 128792B |
| 原Intent候选A（OFF） | 229252B | 128192B |
| 原Intent候选B（OFF） | 228236B | 128176B |

两槽均保留原12条unused+1条RWX警告，没有新增format-truncation等警告。
Flash极紧，不能在未重新审计尺寸时叠加更多功能或插桩。
`.su`局部栈：新planner96B、Prepare24B、Protocol_PrintStatus816B（原560B）。
ProtocolTask分配1024 words/4096B；这些局部值**不是完整调用链峰值或实机stack high-water证明**。
后续功率关闭板测须核对真实栈余量，尤其是STATUS/trace输出负载。

候选A BIN SHA256：`814d6254a29dfe186309f35b00a8dc1752a597f6bc8b51f2254f19dff03fa886`。
候选A ELF SHA256：`84740c33e5dbd222251a7b15a4b7c8dff1989941d056b4cda9094fa3d1a8e391`。
候选B BIN SHA256：`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
原Intent OFF构建的A/B BIN哈希仍与修改前完全相同；候选未写入正式B。

## 离线验证

新增 `tests/test_foc_pwm_common_mode.py`：

- 真实C planner在`-Os/-O2`下遍历5%～95%三相网格，每种优化753573个case（含额外边界case），其中511036接受、242537拒绝；
- 独立边沿/恢复oracle核对所有接受plan，验证三对CCR差值完全相同；对1000个网格case及越界边界逐offset穷举合法性和最小平移；
- neutral、真实A728故障command、无解、高占空比、NaN/Inf/NULL、不支持拓扑/placement/trigger等；
- 真实`FocAdcTiming_Prepare`寄存器mock，确认只生成plan，不写CCR或门极；
- 复跑原真实CCR adapter 10种permit/门极/late/硬关断条件，两个优化级别均通过；
- 预处理后逐函数比较FOC/PI/encoder/保护/原pending入口与尾部，保持不变；
- profile字符串长度<192，defaultOFF及独立preset。

4项共模、7项FSM、3项前次ADC故障回归已定向通过。
全仓回归：**1387项，18 failure /4 error**，585.759秒；日志 `tmp/commonmode-all-regression-20261019.log`。
失败/错误用例名称（含subtest）集合与上一轮 `tmp/intent-adc-all-regression-20261019.log` 完全一致，没有新增失败用例名；不是全仓通过或每个失败内部原因完全相同的证明。
本遍旧 `test_original_closed_loop_updated` 的临时本机 `profile.exe`（PID36660，路径`%TEMP%/tmp8acui1fl/profile.exe`）挂起数分钟。
确认它属于本轮离线测试后，仅结束该子进程，让测试记录非零退出并继续；对应失败用例仍保留，未修改旧测试、参数或断言来吞掉失败。
全仓其他遗留项包括源码/历史镜像基线、本地原始证据依赖、native/Python模拟预期。相关共模/FSM/ADC/pipeline回归通过，不能替代实机验证。
最终 `git diff --check`通过；构建BIN哈希复核与上表一致。

## 后续板测边界（本轮未执行）

先使用新哈希、新B729 baseline单独准备板测脚本，不能复用旧A728/B725 runner去刷这一版。
先仅验证功率关闭计算：零点、FOC<50µs、deadline miss=0、CCR late=0、真实margin、CM拒绝/偏移统计、任务栈与UART。
新版多了planner和统计开销，**尚未测出最坏µs，不得拿旧33.44µs当新版结果**。
之后另行人工确认的空载测试才能观察新开关共模对采样/电流/EMI的影响；遇到异常停机、不自动重试。
窗口通过也不等于断续运动、电角/机械转矩或20rpm速度跟踪问题已经解决。
