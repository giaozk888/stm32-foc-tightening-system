# DOB0.25 正常完整状态机／制动器负载观察

用户要求一次普通完整状态机、负载突变观察，已说明使用制动器，并确认
固定／有防护、可在防护外独立施加和解除、不接触旋转件、可从轻载开始。
触发为人工还是自动未明确，脚本不控制制动器，不假定已存在同步的
制动指令或转矩采样。没有 OFF 配对基线，不把一次 ON 试运行当作已
验证 DOB 抗扰改进。保持原保护和流程，不强制CONTACT或升流。

## 固定镜像与基线

- 镜像：`foc2_app_a/build/TighteningDob025/foc2.bin`，223880 B。
- BIN SHA256 `0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5`。
- ELF SHA256 `53642f7a942df34ecb6df41efac7324f22f9534b360c3c0a59df2c500a0adaa7`。
- 实际上次 B1103 恢复证据
  `tmp/mechanical-ident-restore-1792739878657774600.json`。
  先按旧 gain0.15 身份核验该完整Flash，再安装新镜像身份，禁止改名
  冒充旧诊断。B/boot/config/private 保留。
- 普通240 rpm START，DOB0.25，Ka0.000046875 A/(rpm/s)，FRIC0.105 A，
  BEMF0.00034866 Wb；补偿cap min(25mA,5%IqLimit)，总Iq +/-0.50A。
  正常300rpm超速、20000度行程、8秒rundown、12秒板端lease，原host
  11.95秒兜底STOP。保护／PI／观测器／限幅均不修改。

## 主机准备

新增 `tools/dob025_normal_fsm_board.py`，默认仅文件检查、无设备访问。
复用既有全Flash基线／阶段写入／两次回读／健康确认／校准／时序预检／
STOP及ANALOG SAFE／完整Flash和RAM抓取／物理断电后B恢复流程。
功率关闭前检查任务栈至少原256B门槛、ADC、原配方及全部补偿readback。
正常镜像默认DOB ON，预热前实际补偿为0，无需发诊断ON或MECH RUN。
只发一次普通START；任何保护、准入、通信、关断证据异常立即停止，不重试。

运行时交错 STATUS 与单条 DOB 查询，避免长串阻塞退出路径：记录
speed CTRL/DET/REF、IqRef、位置、BUSY/CONTACT/OUTCOME/FSM补充事件，
DOB估计／有效性／源timestamp、实际compensation／age／state、PI／总Iq／
integral／sat及计数。每条保留自己的源时间；不同UART回复不是同帧，
无全速率转矩或加载时刻通道，不能伪造精确负载阶跃恢复时间。
停机从当前ELF解码80B DOB反馈结构和原FF／摩擦／PWM／fault／timing。

CONTACT允许自然进入，不像空载脚本遇CONTACT就停止。CONTACT之后
进入TIGHTEN/HOLD时参考及控制模式改变，不把故意降速当成DOB退化。
完整OK需当前START的有序STARTED／COMPLETE RESULT=OK和无独立故障，
固件FSM本身约束armed/contact/tightening/no-fault；不强求稀疏UART
碰巧采到每个中间状态。自然TIMEOUT只表示采集完成，不报告拧紧OK。

新增5项主机测试通过：文件身份与B1103；物理条件缺失不接设备；
错误gain阻止START；模拟CONTACT继续并且恰好一次普通START、无SET／
诊断RUN／强制ON；关断缺失／故障／deadline失败拒绝、TIMEOUT不冒充OK。
另复跑正常模式、FSM/ADC健康、START验收、DOB适配器与PWM回归。

## 现场步骤

1. 12V关闭、MCU供电，制动器释放、电机固定有防护。只写非活动A，
   两次完整回读并核对B等区域不变；不激活、不启动。
2. 单独上电确认，无报警、限流0.5A、人员全程在场可立即断电。
   制动器初始释放。校准／时序／栈／准入通过后才发一次普通START。
3. 启动后先不加载，约2秒后从轻载施加，短暂后解除；如设备并非能
   安全独立施加／解除则不执行。重载自然触发CONTACT就让原FSM处理，
   不要求加载器维持堵转，更不手挡转轴。异响、松脱、过热立即断电。
4. 自然结束或原host限时STOP后核验功率关闭／CPUhalt、保存数据。
   人工关闭12V后才恢复B启动选择，B应用不运行。

本记录创建时尚未发送START；实际stage／run／restore证据后续追加。

## 非活动 A 暂存通过，尚未激活

`tmp/dob025-normal-stage-1792741187917267000.json` PASS：在用户确认12V
关闭后只写非活动A，两次独立完整回读通过，B／boot／private／metadata
未变，activation=false、motor_commands=0、输出关闭／CPUhalt。
定向35项、7模块回归全部通过，日志
`tmp/dob025-normal-board-regressions.log`。等待独立上电／无报警确认，
确认前不激活、不发送START。

## 实际一次运行完成

用户独立确认上电／无报警／全程在场后，只执行一次普通START REQ7839。
`tmp/dob025-normal-run-1792741325539315300.json` PASS，原始日志
`tmp/dob025-normal-run.log`；同镜像完整Flash/RAM已保存，未经重试。
校准4000个有效样本、48拒绝、连续最多1；零点1559/1563，校准结果通过。
输出关闭的时序／ADC／任务栈预检通过，任务栈free2532B。

以主机START发送为起点的稀疏状态证据（不是精确硬件转换时刻）：

|约时间 s|观察|
|---:|---|
|0.10|RUNDOWN_START，PRECHECK已通过，尚未armed|
|0.98|RUNDOWN，RUNDOWN_ARMED=1|
|1.5--2.7|约234--242rpm，已接近240rpm参考|
|3.14|DOB补偿约17.89mA，源估计约71.56mA，适配器处于短缺口HOLD|
|3.55--4.35|采到DOB补偿25mA，上限生效|
|4.54--4.87|IqRef多次500mA，稀疏CTRL从182.4降到最低74.6rpm，再回157.5rpm|
|4.96--5.55|稀疏CTRL回升246.6rpm，随后在约231--241rpm附近|
|6.54--6.75|后续重载速度57.2→0.8→0.2rpm，仍为速度模式；IqRef500mA|
|6.59|CONTACT_CONFIRM pending=1、armed=1，尚未确认|
|约6.82|STATUS CONTACT=1、MODE=IDLE（原contact停止确认过程）|
|7.10|TIGHTEN，CONTACT_CONFIRMED=1、armed=1|
|8.27|HOLD，CONTACT_CONFIRMED=1、armed=1|
|8.80--8.81|DONE，OUTCOME=OK；当前REQ7839的COMPLETE RESULT=OK|

PRECHECK可短于50ms状态轮询周期，不能因未采到就伪造一条事件。
原始IQ阶段依次观察80/100/120/150mA、HOLD150mA，DOB在非速度模式
实际补偿归零；不将IQ阶段故意停转算作速度环跟踪差。

本次总Iq命令峰值0.50A，速度段累计饱和0.854006s、最长连续0.411963s；
PI原始项可超过0.50A，不等于已绕过限幅，最后速度帧raw约0.962769A
但ref仍0.50A。DOB实际comp峰值25.000mA，cap命中1048个更新，未提高cap。
有效反馈4237/6780个更新，HOLD275、FADE34；次数不是精确持续时间。
4.92、5.33附近观测到缺口失效后comp已归零，5.82恢复为约2.728mA。
这些仅证明有质量丢点和淡出／恢复，稀疏帧不能确定每个缺口根因。

FOC max33.18824us、deadline miss0、CCR late0，最小PWM提交裕量14.61176us。
独立fault VALID0、FLAGS0，CUR_CONFIRM enter/clear133/133、fault0，
不将正常确认事件解释成保护动作。UDROP/UERR/RXDROP末次均0。
速度段全速率统计最大正超调43.66864rpm，比稀疏STATUS里看到的峰值大；
不可拿稀疏246.6rpm冒称全程最高转速。最后SD/MOE/CCER关闭、CPUhalt，
实际DOBcomp=0。未测真实转矩，不把过程OK当成转矩精度通过。

没有用户提供的精确施加／解除时刻、没有制动转矩通道、没有同条件OFF；
仅能说本次出现制动响应、限幅有效、最终自然完成FSM，不能量化DOB独立
改善、精确恢复时间或证明负载抗扰合格。

## 断电后恢复B

用户单独回复“关了”后执行恢复，
`tmp/dob025-normal-restore-1792741405427869500.json` PASS：B/boot/config/private
未变，B应用未运行，motor_commands=0；metadata1107选择原B，
VTOR0x08040000，SD/BDTR/CCER0、CPUhalt。未再运行电机，未推广覆盖物理B。

## 仅主机字段补充（不重测）

分析发现历史通用fields()只识别大写key，结构化STATUS漏掉mixed-case
`IqRef`，但本次全部原始UART含该字段且已保存，可回溯；未篡改原run证据。
新wrapper增加局部status_fields解析和raw_reply保留，后续不再漏掉IqRef，
不改通用解析器或固件。增加正／负／零IqRef回归，离线验证，无新START。
