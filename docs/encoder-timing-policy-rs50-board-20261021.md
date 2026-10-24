# 编码器时序分层候选：Rs50板测在激活前中止

## 镜像与准备

- 非活动A preset：`MotorParameterIdentificationEncoderTimingDiagnostic`，215060B。
- BIN SHA256：`09ac2082aec995fd6be5e826a887aba2513521319cf13783119157c460fda661`。
- ELF SHA256：`0fff84c68c506b25b9ec0ca956ede8cb5cfe52ff38d54274065bad7859e881ad`。
- 独立精确runner：`tools/motor_ident_encoder_timing_board.py`，基线B836。
- 新脚本3项测试、motor-ident相关合计56项通过，未改控制代码。
- stage：`tmp/motor-ident-rs50-stage-1792503442704022800.json` PASS。
  完整回读，B/boot/private/metadata未变；没有激活A或发送注入命令。

新runner会在注入前验证ENCODER TIME的policy2、warning200us、硬期限400us、
schedule200us、period1000us、age1500us、control2500us；
同时保留Rs100us/L55us、连续拒绝3对退出等原辨识约束。
实际运行没有走到这些前台策略查询，不能声称板端policy2已经通过验证。

## 本次执行

用户重新确认12V开启、无报警、锁轴夹具/防护和接线未变、限流0.5A、
可在现场立即断电后，仅尝试一次Rs50/最多400ms流程。

run：`tmp/motor-ident-rs50-run-1792554543733897200.json`。

首次OpenOCD入口检查报`CPU not halted`，发生在full compare、mailbox提交、
reset和A激活之前。该off_gate要求CPU已经停住，不会自动继续/复位来绕过条件。

- START次数0，Rs注入尝试0，commands为空。
- 串口收到原B的IDLE/FLT1输出；抓停PC为`0x08058c58`，VTOR=`0x08040000`。
- 本次并未进入新A、未执行Rs50，不能归因为新编码器策略、ADC或Rs估计失败。
- 原B为什么已在运行尚无直接证据：可能存在先前复位/重新上电等，不能单凭此收据确定。
- 清理时串口ANALOG SAFE未取得ACK，随后独立SWD关输出并抓停成功。
  因而关闭输出结论来自硬件寄存器检查，不依赖缺失的串口ACK。

## 关闭12V后复核

用户确认12V关闭。没有再次运行辨识或注入，也没有复位。

`tmp/encoder-timing-unactivated-close.log`记录独立全Flash比较与输出检查：

- 全Flash SHA256仍为stage的
  `47dddd4d869a9e9aaec2d103aebcc8c8b65669ea5453946ca0c9073c3fce9058`。
- 原确认B836，pending=0，启动选择始终未改变。
- 因从未提交A试运行，不需要再次写元数据来“恢复B”。
- CPU halted，SD=0，TIM1 MOE/AOE=0，CCER=0。
- BDTR=`0x02002055`并非整个寄存器为0，但使能相关`0xC000`位为0；
  不把保留的配置位误写成输出开启。
- 没有修改Flash、没有执行B应用恢复启动、没有注入电流。

本轮Rs/Ld/Lq均未取得新估计值。后续若重测，应在12V关闭时重新建立并验证
停止/暂存状态，随后另行开启12V；不能绕过入口状态检查，也不能把本次当成
已经完成一次Rs采集或自动进入75/100mA、Ld/Lq。

## 人工授权重试：进入A并执行一次Rs50

用户要求重试，12V关闭时用原stage完整Flash独立比较后重新reset halt，
核验SD/MOE/CCER=0，未重复刷写；见`tmp/encoder-timing-retry-ready.log`。
重新确认12V开启、无报警、锁轴/防护/0.5A限流及现场立即断电条件后，
执行`tmp/motor-ident-rs50-run-1792554750041524400.json`。

本次真实进入新A，正常5秒health确认复位、零点、FOC时序和任务栈预检通过。
ENCODER TIME在注入前后均验证policy2/400us及各独立契约；
恰好发送一次RS50命令，未START、未重发、未升档。

### 终止原因不是编码器：Rs可解释hold-gap累计预算耗尽

Rs start=8001286us；失败now=8198203us，即196.917ms。
末态MID_ABORT4、MID_TIMING8、N0。稳态32行记录从200ms开始，
因此本次尚无估计行，不能输出Rs，亦未进行Ld/Lq。

| 同一失败点 | 数值 |
|---|---:|
| 上次已接受seq/us | 161597 / 8198103 |
| 本次seq/us | 161599 / 8198203 |
| delta_seq / delta_us | 2 / 100us |
| physical ADC seq / frame seq | 161599 / 161599 |
| hold_before / hold_now | 539 / 540 |
| 当前gap解释所需hold_delta | 1 |
| 此前接受gap events / skipped | 16 / 16 |
| 单次最大已跳过pair | 1 |
| 累计预算 / 单次预算 | 16 / 2 |

`MotorIdent_RsExplainedGap`中ds2、dt100、hold_delta1均满足局部解释条件，
但已累计skipped16，再收这一次将到17，超过MID_RS_MAX_SKIPPED_PAIRS16。
该函数拒绝后TIMING只记录flags1（序号差非1），其flags未直接编码预算原因；
必须结合gap统计和源码判断，不能误称物理ADC丢样或100us长间隔违规。
没有为了完成采集而改预算、补样、放宽保护或立即再测。

辨识电流样本reject74/good3848，最大连续reject2，未触发连续3对退出；
这与16次判别器hold造成的参考序号间断是不同统计，不可混为一谈。

### 新编码器策略与时序证据

- encoder attempts6737 / successes6737 / failures0；timeout、DMA error、
  schedule miss、control stale均0；first encoder fault valid0。
- 成功事务最大248us，小于候选400us。>=200us成功慢计数前0/后77；
  这个增量包含注入前后主机命令和停止后读出，**不是仅196.917ms测试窗的计数**。
- 当前guard cl_flags/cl_fault_valid/adc_fault/foc_fault均0、encoder_valid1。
- FOC wall max36.48235us，deadline miss0。
- actual CCR commits137553、late0、min margin15.15294us。
- 一次有界运行仅说明本会话未触发编码器故障，不是完整WCET资格化。

### OFF及恢复

用户确认12V关闭后，通过原bootloader SET_CONFIRMED_SLOT B流程恢复，
停在B入口，没有运行B应用，未再次注入。

- restore `tmp/motor-ident-rs50-restore-1792554819544503300.json` PASS。
- 确认B840、pending0；B应用内容和boot/private未变，A候选仍保留。
- SD0、BDTR0、CCER0、VTOR0x08040000、CPU halted。
- 全Flash SHA256 `7d5d7eeab10c7d9c1f33ca1a1604dd962de19c1e9f64a7b03d4a37f18b62c061`。

本轮固件未再改；下一步应针对Rs稳态样本准入与hold-gap预算的关系独立审查，
不能继续把此次退出当成编码器事务超时，也不能声称Rs已辨识成功。
