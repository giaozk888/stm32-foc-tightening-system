# 同镜像 DOB 0.25 / 0.5 各十次实机空载对照

用户确认12V关闭、MCU供电、转轴解锁且电机空载固定有防护、接线未变、12V/0.5A、整组在场可断电，并允许仅更新非活动A。独立上电/无报警确认前不得激活或发START。

## 隔离与不变量

新`DobGainAbCandidate`继承已采五窗的`DobRealTraceCandidate`，正常240rpm START、CONTACT20rpm、DOB观察下限10rpm/反馈下限20rpm、20000°/8秒rundown/12秒板端lease。保留原PI、S曲线、Ka=0.000046875 A/(rpm/s)、摩擦0.105A、BEMF、20kHz FOC、单周期PWM流水、采样/角度链、CUR_CONFIRM、CURRENT_INVALID、保护及IRQ。不抬高保护，正式B与正式0.25配置不变。

诊断宏仅在A的显式原始采集profile可用。默认DOB OFF、gain0.25；新增RAM-only命令`MOTOR TEST MECH DOB FB GAIN 250000`或`500000`，拒绝其他值。空闲、无start/stop请求、无fault且SD/MOE/AOE/CCER全部关闭才能修改，修改会清空该适配器并保持OFF；再走原受限ON命令。运行中不可改，无存储/电机启动动作。补偿上限仍25mA与5%Iq上限取小者，slew0.25A/s、fresh2ms/hold5ms/expire20ms、总Iq±0.50A均不变。

原正式normal profile仍保留gain==0.25的编译断言；只有该显式诊断profile有例外。共享header/绑定新增代码均由宏隔离，不修改观察器或实时电流反馈。先前Simulink报告的源码哈希代表完成仿真时的快照；这些后续诊断源文件编辑不更改原生仿真DLL/MEX、原始数据或旧结果。

## 构建、回归与镜像

- A编译成功，BIN224228B，RAM130864/131008B，Flash224228/229376B。既有未使用变量/函数和RWX链接警告仍存在；栈和时序运行前继续按原准入检查，不降低门槛。
- BIN SHA256 b63e5bfb9662ee808f2424f75512de3ef4135ad0f9fd2365722f2c6f28357535。
- ELF SHA256 996078b0b396450e5c0b79984309eec59506b3f7831bffac79aec416b5f71f84。
- 新2项固件回归（Os/O2精确增益/各忙碌输出fault门控/清零OFF/补偿限幅；预处理关键函数一致）。新5项主机模拟回归（恰好交替20轮、故障立即停不重试、增益错配停止、缺现场确认不访问设备、增益命令和回读后才走原路径）。既有3项原始采集和3项反馈回归通过。模拟打印的20轮不是实机运行证据。

## 执行计划

`tools/dob_gain_ab_twenty_board.py`无参数仅验证文件。`--stage-off --drive-off-unloaded-fixed-guarded`以`tmp/dob-real-restore-1792755294485030100.json`的原B停机回退为基准，只写非活动A、两次全512KB回读、核验B/boot/config/metadata不变，停在halt/输出OFF。

新鲜上电、无报警、整组20轮在场可断电确认后，`--execute-twenty STAGE_RECEIPT --operator-present-twenty-drive-on-no-alarm-05a`按[.25,.5]×10。每轮重新启动同一A、原校准/时序/栈/准入通过，功率关闭时选增益并回读，再明确ON、一次START。任何独立保护、配置错配、关断证据异常都停止，不重试或继续。空载自然RUNDOWN_TIMEOUT不是拧紧完成，但无独立保护且关断证据正确可作为空载观察样本。

每轮保存全Flash/RAM、实际gain RAM回读、原加/减速误差积分、匀速/低速MAE、超调、Iq/积分器峰值、饱和时间、FOC wall/deadline/CCR、DOB/补偿统计，以及约2秒后的固定192ms原始Id/Iq/速度窗口。短窗不是整轮完整波形，不是独立负载真值。

原程序`normal.classify`仍强制独立故障/时间/输出关断检查。上一轮精确安全receipt及Flash哈希/metadata/B完整性通过后才下一轮。每组10个独立轮次报告均值/样本标准差及10对0.5−0.25差值，不用stable确认时刻替代加速跟踪误差。顺序交替但未随机化；空载不能证明真实负载抑制或扭矩精度。

20轮完成/提前停止后，要求人工关闭12V；确认后只用最后真实停机receipt恢复原B启动选择、不运行B应用，不自动采用0.5。

## 首次暂存被初始停机检查拦截（未擦写、未启动）

`tmp/dob-gain-ab-stage-1792761211309519300.json`保留失败：首次OpenOCD init后原off_gate要求CPU已halt，但实际回复`CPU not halted`，脚本在任何flash write/verify/reset激活之前退出。没有发START，start_attempts=0。finally的安全关断成功：SD/MOE/PWM关闭，MCU debug-halt；全512KB保存为同名`-failed.bin`。

离线逐字节比较该备份与`dob-real-restore-1792755294485030100.json`的原B基准：全Flash完全相同（含旧A、B、boot、config和metadata）。备份SHA256为`9dc1490b3771abf3bda3b59c66fb56a96bec49712a9f2626c46c1e149ad29ab9`。故没有写入新A、没有破坏B回退；只确认初始CPU停机前提不成立，不将其归因于电机保护故障。保留12V关闭，未自动重试暂存或启动电机，等待人工决定。

## 人工确认后重新暂存成功，尚未激活

用户随后回复“符合”，按12V关闭且允许重新暂存处理。`tmp/dob-gain-ab-stage-1792761339765743700.json`PASS：新诊断A写入、两次完整512KB回读通过，原B/boot/config/metadata未变；activation=false、motor_commands=0、SD/MOE/PWM关闭、MCU halted。此后必须取得独立上电/无报警/20轮全程在场确认，才可执行20轮；当前未激活或发START。

## 实际9轮后主机中断与手动续跑准备

`tmp/dob-gain-ab-batch-1792761485941598100.json`实际保存9轮（0.25五轮、0.5四轮），并在第10次启动预检时因对话中断失去主机进程。最后`dob-gain-ab-run-1792761887740001700.json`start_attempts=0，未发START，不是电机保护触发。原进程已不存在后，仅执行安全关断/MCU halt，备份`tmp/dob-gain-ab-interrupted-safe-1792762003887427100.bin`；输出OFF/halt证据通过，原始批次标记interrupted_no_retry，未自动续跑。

用户明确要求继续，并新鲜确认12V关闭/现场条件不变。专用`tools/dob_gain_ab_remaining_board.py`只接受这一确切9轮已完成+第10次零START中断来源，核验每轮原保护、gain RAM、Flash/RAM/CSV及B/boot/config。任何原START尝试或保护失败均禁止该入口。新增5项回归通过：仅补第10～20轮、人工授权和供电门控、拒绝非零START、故障首次即停。模拟输出不是实测完成证据。

`tmp/dob-gain-ab-resume-restore-1792762311484339900.json`恢复原B启动选择PASS，未运行B；派生中断安全closure不是合格运动记录。随后`tmp/dob-gain-ab-remaining-stage-1792762326834760100.json`同一A两次完整回读PASS，无需重新擦写，B/boot/config/metadata未变，activation=false、motor_commands=0、输出OFF/MCU halted。前9轮不重复，仅准备0.25五轮、0.5六轮；等待独立上电/无报警/剩余11轮全程在场确认。

原第9轮与续跑第10轮之间存在人工停机间隔，属于第5对跨停机配对。报告必须明确这一间隔，附带排除该对的敏感性统计及续跑分组结果，不能称为严格连续或随机化的20轮试验。

## 已补齐实际20轮，等待关12V后的B恢复

新鲜上电/无报警/剩余11轮全程在场确认后，`tmp/dob-gain-ab-remaining-batch-1792762816850175300.json`PASS：原9轮保持不变，新完成第10～20轮11次；两组各10轮，实际gain命令与RAM回读一致，原预检/保护/关断检查通过，无自动重试。最后一轮已保存Flash/RAM/原始固定窗，SD/MOE/PWM关闭、MCU halted。尚需用户独立确认12V关闭后，只恢复原B启动选择；此处不声称已恢复B或关闭现场电源。

### 安全收尾与独立汇总已完成

随后用户确认“关了”，`tmp/dob-gain-ab-restore-1792763799510887400.json`恢复原B启动选择PASS，B应用未运行、motor_commands=0、应用和私有配置保留，输出OFF、MCU halted。`tools/report_dob_gain_ab_twenty.py`只读独立核验实际20轮、原9轮来源哈希/零START中断、各轮gain回读、Flash/RAM/CSV、原保护/时序/限幅及关断。全体及排除跨停机配对均显示0.5的主指标均值略差，未自动采用。详见dob-gain-ab-twenty-results-20261023.md。
