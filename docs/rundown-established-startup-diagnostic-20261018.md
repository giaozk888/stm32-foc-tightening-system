# 起转建立门控与 NO_ROTATION 定向诊断

## 结论与范围

修复的是应用状态机的假 CONTACT / 假 OK，不是声称已经解决物理起转问题。
20 rpm → 2.77 rpm 的速度跟踪根因仍需新板测证据。
本轮仅编辑、编译、离线测试，没有刷板、复位、串口/调试器连接、START，
也没有更改板端 B 启动选择。新的构建目录与历史镜像分离。

基线提交：`5eeae2ebf55778b6300949874f4ad7508cc5259e`。

## 1. 原漏洞

原 RUNDOWN 仅检查低检测速度、高同向 Iq **需求**及持续时间。
静止启动时同样能满足这些条件；之后分段电流/保持按时长走完就返回 OK。
它并没有证明曾成功起转，也没有独立的物理接触/扭矩证据。

## 2. 新起转门控

`firmware_common/tightening_rundown_guard.h` 是 A/B 共用的纯应用判据。
每次接受 START，现有 `TighteningRepeat_ResetCurrentCycle()` 都将其重置为
`RUNDOWN_NOT_ESTABLISHED`，不能继承上一轮的 armed/candidate。

| 宏 | 初值 | 含义 |
|---|---:|---|
| RUNDOWN_ARM_SPEED_RPM | 10 rpm | 最低解锁速度 |
| RUNDOWN_ARM_SPEED_RATIO | 0.50 | 相对本次命令的解锁比例 |
| RUNDOWN_ARM_CONFIRM_MS | 100 ms | 两路速度连续满足的时间 |
| RUNDOWN_ARM_MIN_TRAVEL_DEG | 3° | 同一合格区间内同向净机械位移 |
| RUNDOWN_ARM_MAX_GAP_MS | 30 ms | 缺观测时重置连续候选 |
| RUNDOWN_START_TIMEOUT_MS | 1500 ms | 允许建立起转的初始窗口 |
| RUNDOWN_START_DRIVE_IQ_A | 0.30 A | 有明显同向驱动需求的判据 |
| RUNDOWN_START_DRIVE_MS | 250 ms | 高需求必须持续的时间 |

解锁必须同时满足：

- 编码器有效、输入为有限数；
- 控制速度和独立检测速度均沿命令方向达到
  `max(10 rpm, abs(command)*0.50)`；
- 上述速度连续满足至少 100 ms，且在这个**同一候选区间**内同向净位移 ≥3°。

用实际 elapsed 时间而非调用次数计时；断流大于30ms清除连续候选。
不接受单一瞬时速度点或单次位置跳变作为运动证据。方向相反、检测速度
未达标、位置没有前进、编码器无效都不能解锁。初值是针对当前20rpm低速
实验的可审查参数，不是工业产品整定结论。

## 3. CONTACT / NO_ROTATION / OK

- CONTACT 的原速度、电流需求、250ms持续判据保持不变，但开始累计候选和
  正式确认两处均要求 `RUNDOWN_ARMED`。
- 尚未armed，RUNDOWN elapsed ≥1500ms，且同向IqRef ≥0.30A持续至少250ms：
  进入 `TIGHTEN_STATE_FAULT`，结果为新增 `TIGHTEN_OUTCOME_NO_ROTATION`。
- 需求不足0.30A时不会谎报“已经给足驱动仍不起转”；原8s/行程中止仍有效。
  因此1500ms不是无条件必停时间。任务10ms采样、调度延迟可能增加实际观察时间。
- 复用现有 process fault snapshot、COMPLETE事件及结果打印。NO_ROTATION枚举
  追加为7，既有枚举值不变。保护闭环构建复用 `ProtectedLoop_Stop()` 原子关闭
  SD/MOE/CCER、失效pending并结束会话，不制造 RUNNING+SD低的健康检查误报。
- HOLD 要返回 OK 时再次要求 `rundown_armed && contact_confirmed`；否则走
  NO_ROTATION，不会输出OK或增加成功周期。没有自动重试。

“运动建立+软件接触”仍不是独立物理接触或扭矩精度证明。

## 4. 诊断记录

`RundownDiagnosticTrial` 继承 `RundownGuardTrial` / 既有 SB3 设置，
仅额外开启 `FOC_RUNDOWN_DIAGNOSTIC=1`。普通门控版不开扩展采样。

复用原 `cl_startup` 存储而非再分配一个大环。扩展为32帧、每帧124B，
另有1帧独立终止/首故障上下文，结构总4112B。从RUNDOWN最初一个完成的
外环观测开始，保留最先32个至少相隔50ms的观测，约覆盖1.55s；满后不覆盖
起转历史。离开RUNDOWN冻结；之后的分段/保持不会再覆盖窗口。
真正首硬件/保护故障继续沿既有路径先关闭输出，再记录并冻结。
NO_ROTATION使用原STOP先关输出，允许一次post-stop终止注记，不覆盖首硬件故障。

每帧包括：

- 配方速度命令、斜坡中的speed_ref、控制/检测/瞬时速度；
- IqRef、Iq、Id、Iq_error、Vd/Vq及原积分值、接近电压矢量上限的标志；
- IU/IV最新原码、ADC seq、validator state、current_path；
- 编码器raw、最近一次accepted delta/dt、时间戳、glitch streak、valid；
- 机械累计角、电角和原预测电角；
- pending三相CCR、pending valid/source seq、CCR1/2/3回读、actual提交计数；
- armed、contact candidate、状态、控制模式、SD/MOE读回标志。

**含义限制：**

- 这是20Hz抽取的外环完成快照，不是连续20kHz ADC pair，也不是所有模拟量
  同一采样瞬间。拒绝帧上的Iq/Id可能保留上一正常结果，应结合current_path。
- encoder delta/dt属于最近一次accepted外环更新，不是两张50ms快照间的差值。
- PWM applied字段严格标为 `PWM_applied_preload_readback`：表示最后写入的
  CCR preload回读，不证明功率桥端子电压、实际有源latch或真实相电流。
- 20Hz不能排除短于50ms的毛刺。完整起转和终止窗口能帮助收窄持续不跟踪，
  但不能凭这一个窗口独立证明电角度、相序、转矩效率或物理电流极性。

周期记录仍在既有1kHz MotorControlTask hook，先做时间门控，到期才短临界区
快照。没有新增20kHz周期记录、printf/UART、动态分配或中断优先级变更。
仅在诊断版accepted encoder publication尾部保存delta/dt，不改估计结果。
原故障路径仍可调用二进制快照，输出关闭在前；没有ISR格式化。

为了省Flash，扩展诊断版不编入旧逐帧UART人类格式化；`MOTOR TEST STARTUP`
只返回schema=2、行数、周期、字节数。全部详细解码在Python。

## 5. 离线读取与调查分支

只读取人工板测后已保存的匹配ELF/SRAM，不自动连接板子：

```powershell
python tools/rundown_startup_decode.py --elf <本次匹配的foc2.elf> --sram <已保存SRAM.bin>
```

也可传 `--trace-bin <已抽取cl_startup.bin>`。校验4112B布局、冻结状态、
观测顺序；输出原生float精度的JSON，保留完整链、文件SHA及证据限制。
ELF符号大小校验不能代替试运行收据的Flash/ELF/SRAM身份绑定；报告明确
`capture_identity_verified=false`，不伪称已证明匹配。默认编码器方向假设-1，
可显式传入原固件配置，绝不写回控制参数。

| 观测 | 调查分支（不是自动定责） |
|---|---|
| Iq跟随IqRef，速度仍低 | 机械负载、电角度、转矩效率、速度控制 |
| Iq不跟踪/反向、Id增大、Vdq近限幅 | 反馈映射/符号、电角度、采样、相位对应 |
| delta/dt重算速度与instant不吻合 | dt/速度发布或估计链；先排除被拒绝encoder样本 |
| raw角、valid、glitch、时间戳异常 | SPI/DMA、unwrap、编码器链 |

需要人工检查记录，不会依据这些分支自动翻转相序、反馈符号或调整PI。

## 6. 构建与代码隔离

在各A/B目录执行：

```powershell
cmake --preset RundownGuardTrial
cmake --build --preset RundownGuardTrial --parallel 6
cmake --preset RundownDiagnosticTrial
cmake --build --preset RundownDiagnosticTrial --parallel 6
```

| 槽/配置 | Flash /229376B | RAM /131008B |
|---|---:|---:|
| A RundownGuardTrial |228924|127992|
| B RundownGuardTrial |227916|127976|
| A RundownDiagnosticTrial |228220|130080|
| B RundownDiagnosticTrial |227204|130064|

诊断版较小是因为只保留二进制解码入口，不是因为删保护或改链接边界。
普通版100Hz `TighteningTask`单独使用-Os，节省新增门控所需Flash；没有
改变FOC/PI/编码器数学或20kHz架构的优化设置。静态帧：普通TighteningTask
296B、MotorControlTask208B；诊断版分别416B、336B，另有StartupFrame88B。
这些不是运行时栈高水位证明；原任务栈配置未变。
诊断版RAM余量A仅928B/B944B，不能无预算继续增加窗口。

与基线预处理函数对照通过：电流FOC、原编码器/速度控制、reset、pending
entry/stage、ADC、validator、CUR_CONFIRM底层、TIM7和timer-health不变。
诊断版encoder函数仅增加两条accepted结果记录赋值；删除这两条后控制函数
一致。A/B三种新旧配置的 `foc_adc_timing_stm32.c.obj` SHA完全相同。
未改PI、Clarke/Park、SVPWM、限流/限压、保护阈值、电角零点、方向、相序、
极对数、PWM/ADC频率、NVIC优先级或A/B启动逻辑。

A guard BIN SHA：`b3de4eb65016178dc65564dfa64f5229d93bc308f7161d63e6fd39485c018c9f`。
B guard BIN SHA：`f06fb9d7eac6a42daee5475cb4d9569e2137423c32e41099b2959a9de7560035`。
A diagnostic BIN SHA：`a9c5cf73e0d32540d90557d2c3f69ec7cfbd8ff94939261741bfc21604636234`。
B diagnostic BIN SHA：`ece68fd802e48963ee3e381dd9d344dbd261e6039d22129f5ff04dc641358414`。

既有unused-function/variable、Pigweed上游和RWX LOAD warning保留；
新normal源码warning集合与基线对照没有新增。不能宣称构建零warning。

## 7. 测试

`python -m unittest discover -s tests -p test_rundown*.py -v`：最终14项PASS。
包括真实C guard、直接抽取A/B固件switch编译执行（不是复制Python状态机）：
正常运动→armed→接触→所有原后续阶段→OK；静止/2.77rpm/单速度毛刺均只能
NO_ROTATION而非CONTACT/OK；HOLD终态双门控；原timeout/stop/torque abort；
不足100ms/短高电流需求/方向/位移/encoder无效/缺观测；保护版原STOP关断；
窗口不可被HOLD覆盖、首故障不可被终态覆盖、二进制布局/离线解码及控制隔离。
C回归在-Os/-O2下均执行，-Wall/-Wextra/-Werror，无设备访问。

首轮全量1203项，1190通过、9FAIL/4ERROR，日志`tmp/rundown-all-tests.log`；
13个失败/错误名称与上一轮`tmp/sb3-all-tests.log`完全相同。
补齐最终测试、冻结固件源码后再次全量：**1212项，1199通过、9FAIL/4ERROR**，
耗时266.738s，日志`tmp/rundown-final-all-tests.log`。全部14项新测试也包含在
最终全量中并通过。失败/错误名称与上一版完全相同，没有新增，也没有改旧
断言、删除测试或放宽证据身份来制造PASS，不能宣称全量全绿。
仍未通过的历史项涉及：源码字符串位置/旧TIM7优先级文字断言、旧哈希冻结、
旧主机抽取夹具、固定旧镜像身份与私有基线访问。它们保留为未解决项。
历史模型/固定旧镜像测试不是新固件的物理验证，不因此声称真实闭环合格。

假 CONTACT 已修复，起转失败诊断已就绪，等待人工低速上板验证。
