# CONTACT20 rpm / DOB观察10 rpm：独立候选A

按用户明确选择：保持原状态机流程，不增加30rpm末段目标；只将正常A
配方CONTACT速度设为20rpm，DOB最低观察速度设为10rpm。
使用新预设 `TighteningDob025Contact20Observe10Candidate`，继承正常
`TighteningDob025`，不重建／替换之前已板测的固定镜像。

## 两项配置与保持项

- CONTACT：启动时加载原配方后，以RAM overlay将contact_rpm设为20。
  只在新候选启用，V1参数布局／公共默认值10rpm／B／KVS记录不改，
  SAVE仍禁用。GET CONTACT_RPM应返回20，防止旧Flash值悄悄覆盖新选择。
- 原FSM算法不改：门槛仍是min(CONTACT_RPM,0.70*旋入实际峰值速度)，
  使用检测速度绝对值、包含等于边界；正常240rpm峰值下为<=20rpm。
  先armed，正向Iq需求>=0.30A，持续250ms才确认。速度>22rpm或
  Iq需求<0.27A取消候选，迟滞／持续确认规则未改。
- DOB观察下限：机械rad/s，10rpm=1.0471975511965977rad/s。
  观察器模型min_speed_rad_s与原运动准入共用这一值，因此10..20rpm
  可经原质量筛选与预热后输出观察值；低于10rpm仍无效／复位。
- 本轮按“观察下限”而非“低速补偿范围”实现：新鲜反馈源仍需
  |omega|>=2.0943951023931953rad/s（20rpm）。10..20rpm的有效观察帧
  不允许刷新feedback.last_valid_us，原5ms保持／20ms前淡出归零不改。
  一周期流水线可在边界刚跨过时消费上一张20rpm有效帧一次，这是既有
  源时间语义；不是把当前低速帧冒充新鲜补偿。10..20rpm观察连续性可
  保留已积累的预热，因此回到20rpm以上后的恢复可能与旧复位行为不同。
- DOB反馈gain0.25、补偿cap min(25mA,5%IqLimit)、总Iq+/-0.50A、
  原anti-windup／0.25A/s slew／2ms freshness保持不变。
- 不改PI、S-curve、Ka0.000046875、摩擦0.105A、BEMF0.00034866Wb、
  FOC20kHz、one-cycle PWM、CUR_CONFIRM、CURRENT_INVALID、采样、
  角度链、电角零点、IRQ、独立过流／超速／外环／编码器／时序保护。
- 普通目标仍240rpm，不是30rpm；300rpm超速、20000度行程、原8秒
  rundown及12秒lease保持。未新增DOB辅助CONTACT／卡滞判别。

## 新诊断信息

启动标记：
`DOB C20/O10: CONTACT=20rpm OBS_MIN=10rpm FB_MIN=20rpm RAM_ONLY=1`。
新增只读 `MOTOR TEST MECH DOB SPEEDS` 返回
`CONTACT_RPM=20 OBS_MIN_MRPM=10000 FB_MIN_MRPM=20000 RAM_ONLY=1`。
原MODEL查询MIN_W_MRAD_S应为1047（整数输出截断），其余机械参数不变。

## 修改文件

- foc2_app_a/CMakeLists.txt、CMakePresets.json：独立opt-in预设及正常A依赖。
- firmware_common/dob_contact20_observe10.h：明确分开的三个门槛／速度源资格。
- firmware_common/mechanical_dob_monitor.h/.c：只在新宏下将观察下限改10。
- foc2_app_a/Core/Src/main.c：配方加载后的RAM CONTACT20覆盖、原反馈源
  20rpm资格检查、启动标记。
- firmware_common/mechanical_dob_binding.inc：只读速度配置查询。
- tests/dob_contact20_observe10_host.c、test_dob_contact20_observe10.py。
- tests/test_mechanical_dob_monitor.py：旧参数核对改为读取旧预设实际
  编译的预处理单元，避免正则误读未启用的新分支；期望值不放宽。
- README.md：新增候选入口说明，正式选用预设不自动替换。

## 编译与离线验证

新A编译通过：BIN224180B，FLASH224180/229376B，RAM130768/131008B。
不缩stack/heap，既有unused/RWX警告仍在；不宣称无警告。
BIN SHA256 `967f38e949a38ffa980bee77cedf67cd0949f8e7ef03be89e0e5a87944d7420e`
ELF SHA256 `3289e15a0e7830451c58f42c6a51d15646150ca7b2b2330ceb1e5d6d411d3467`。
B review构建通过，BIN保持
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
旧正常A BIN保持
`0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5`。
新候选尚未刷板，旧机械／正常A pin脚本不得修改hash冒认该镜像。

新增4项测试：真实FSM／观察器／适配器在-Os/-O2下检验20边界包含、
20.01不满足、Iq不足不满足、250ms持续／22rpm退出／30mA迟滞／
STOP／保护关断；双向10/15rpm观察有效但无新鲜低速补偿、20rpm补偿
可用、降速按原保持淡出、9.9rpm无效、饱和仍拒绝；实际编译的启动
overlay在旧配方加载后执行，只改rundown/travel/contact；存储保存
实际预处理体仍return0；FOC／IRQ／guard／功率／FSM task／原准入
与已板测正常A的代码体一致。共享V1默认及B未改变。
最初新增测试中的源码单元定位、mock边界／测试缩进问题已修正，
最终定向测试4/4通过，日志`tmp/dob-contact20-observe10-focused3.log`。
完整相关回归结果完成后追加，不将测试fixture问题当成实机故障。
首次完整回归在旧固定模型参数测试处发现其直接正则解析源码而误读
候选宏；改为实际旧SHADOW预设的mechanical_dob_monitor.c预处理结果
后5/5通过，再完整重跑。非候选仍检查原全部模型数值，非改成忽略差异。

最终完整相关回归192/192通过，44模块各自独立进程执行，记录于
`tmp/dob-contact20-observe10-regressions-final.log`。包括新候选／旧正常／
各增益／模型／筛选／状态机／准入／时序／ADC／PWM及反馈开关主机测试。
相关已跟踪文件`git diff --check`通过；本轮无硬件访问、刷写或START。

## 之后的人工验证（本轮不执行）

保持独立OFF-stage／powered-confirm／校准与输出关闭时序栈预检／
一次START／STOP和FlashRAM保存／物理断电后B恢复流程。
先核对GET CONTACT_RPM=20、DOB SPEEDS三门槛及MODEL min1047。
对短暂制动观察是否取消CONTACT候选，对持续制动观察250ms确认；
与原10rpm相比可能更早确认，不能默认误触发率不变。
观察10..20rpm区间valid/age、Id与电流质量／饱和原因，不要求所有点
有效；验证低速观察不注入额外补偿。保护或关断异常停止，不重试。
低速观察可靠性与更早CONTACT的工艺适用性尚未实机验证。
