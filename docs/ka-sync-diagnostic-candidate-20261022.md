# Ka 电流/编码器共同时间基准短窗候选

本轮只补齐独立 candidate A 的诊断记录、解码和离线验证。
未刷板、未复位、未发START、未改变当前B启动选择，正式A/B和原长窗诊断保留。

## 为什么采用独立短窗

旧长窗只保留100ms均值和滤波速度端点，无法恢复20ms滤波内的动态。
新候选保持现有S-curve/PI/保护不动，记录64个连续约1kHz观测点，
首末间隔典型63ms（每个点另含前一encoder区间），不是整段2.4s原始波形。
编译参数 `FOC_KA_SYNC_START_US` 默认600000，从本次速度诊断开始计时，
可在单独构建中选择0..7000000us的其它短窗，不能改变lease/自动启动/自动扫窗。
先证明时序和测量链，再准备长段独立加减速辨识，不把短窗强行用于标定Ka。

诊断默认OFF：`FOC_KA_SYNC_DIAG`。
新preset `KaSynchronizedDiagnostic`，与旧KAI/AAC/startup环互斥，Ka=0、FRIC=.105A、BEMF OFF。
不增加大堆内存，不减RTOS heap或栈，不更改串口波特率/控制与采样频率。

## 电流快照与时间语义

仅新诊断构建在既有FOC计算发布Iq处，增加独立快照：

```text
version变奇数
current source ADC sequence
current source_us（既有cl_frame.source_us）
publication_us（同AS5047P_DmaNowUs时钟）
measured Iq
version变偶数
```

使用DMB保证发布顺序。任务侧读取前后版本一致才接受，最多2次，不关IRQ等待，
没有global mask/优先级/保护修改。不能同时取新Iq与旧source timestamp。
版本奇数/尚未发布/中途变化都不假造有效电流样本。

必须区分：`source_us`是现有ADC pair软件读取/接纳时间，**不是新测量到的模拟ADC采样孔径**。
encoder时间是现有SPI接收sample_us，**不是外部仪器测得的转子瞬时位置时间**。
二者共享1MHz时基，所以现在能够量化软件采集链差值，但不能声称消除了ADC/SPI物理采样延迟。

在ADC路径内只增加整数读写、float原值拷贝、DMB和DWT读数/最大值比较。
`publish_cycles_max`记录新增发布片段的最大周期数（可包含该片段被更高优先级IRQ打断的时间）。
它不是整个FOC额外开销的独立完整测量；版本发布外的编译器spill/测量自身等仍体现在原FOC wall。
原deadline保护保留，新增ISR开销是否满足实机时序仍须功率关闭板测，不能用host测试代替。

## 任务侧每点记录

紧凑二进制，每点18B：

- encoder实际间隔，1us精度；首点encoder绝对时间保存在header。
- task读取时刻相对encoder的年龄，1us精度。
- current source时间相对encoder时间的有符号差，1us精度。
- current ADC序号增量；首点绝对序号在header，支持32位回绕。
- raw encoder增量及header的起始raw，可恢复原始14位角度和连续机械行程。
- 实测Iq，0.1mA分辨率。
- 控制滤波速度，.01rpm分辨率。
- 同点摩擦补偿命令，0.1mA分辨率。
- 仅用于诊断的LPF(Iq-friction)，0.1mA分辨率。
- 数据缺失、间隔/序号异常、范围溢出、电流或encoder过期、命令饱和标志。

范围不够会明确标坏，不以饱和值冒充真实值，不改变控制样本准入或保护。
例如电流表示范围约±3.276A，比独立4A保护小；超出只让本条诊断记录失效，
绝不会把3.276A变成新电流保护限值。

任务内的诊断LPF使用与现有速度完全相同的 `alpha=dt/(.020+dt)`，
输入是快照Iq减当前friction；在采集短窗之前就已连续更新，header保存首点之前的精确float状态。
它不写回控制器，不替换速度/电流反馈，不重新设计PI。
由于Iq采样源时间与encoder时间可能略有差异，单纯同LPF仍不是“已经完全对齐”；
原始Iq与两个时间戳同时保留，允许离线按实际时间进一步插值/比较。

## 无新增运行期逐点UART负载

满64点即冻结，不滚动覆盖。MonitorTask不打印逐点消息，原周期保持100ms。
所有数据在STOP、输出关闭、MCU停住后从完整RAM回读解码。
不为了保存1kHz波形在ISR里printf，也不往现有115200串口硬塞高频日志。
原FF统计/保护状态查询仍可用。

## 解码

文件工具 `tools/ka_sync_report.py`：

```powershell
python tools/ka_sync_report.py --receipt RUN.json --elf foc2_app_a/build/KaSynchronizedDiagnostic/foc2.elf
```

校验同一轮精确BIN/ELF/Flash/RAM和symbol边界，拒绝旧KAI ABI。
解码输出逐点：encoder/task/current_source绝对时间、ADC序号、raw角度、机械连续位移、
由raw增量和真实dt恢复的瞬时rpm、滤波rpm、实测Iq、friction、诊断LPF和质量标志。
可量化current相对encoder时间差、在任务读取时的current年龄。
在两个有效电流快照之间可按时间插值到encoder时刻；没有两侧点时返回null，不外推。
插值只针对约1kHz任务快照，不声称恢复了所有20kHz电流样本。
同LPF重放允许0.16mA量化误差；短窗不足、源时间非单调、重建序号/时间不一致明确报告。
不自动挑选延迟、不反转方向、不输出“最优Ka”。

## 编译与测试

- 新诊断A：Flash/BIN219100B，RAM130888/131008B，余120B，静态余量很紧。
- BIN SHA256 `5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136`。
- ELF SHA256 `f00c940b6f868f4c1f4c88c028db23742dd7c33412ddac3a516256da17b68ed3`。
- 正常A重新编译通过，BIN仍为`6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f`。
- B构建通过/无待构建项，BIN仍为`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
- 旧KAI长窗BIN未重新生成，仍为`cd9f970c4ddfb3ce8ddb9f2e13e1046441d5644bb05df01e493f726d570fb8be`。
- 新构建与正常A均13条既有unused/RWX警告，无新增warning/error。
- 编译器静态stack-usage：MotorControlTask本地帧280→328B；KaSync_Observe局部帧56B；
  ProtectedLoop_AdcIrq本地帧仍184B。它们不是完整最坏调用链或运行期高水位，
  上板必须保留既有MotorCtrl栈余量检查，不能据静态局部帧单独宣称栈安全。
- 新同步诊断4项，加既有Ka相关25项、speed系列88项，共117项相关离线测试通过。
  覆盖实际C -Os/-O2、版本读、时间/ADC序号回绕、紧凑量化、超量程标坏、满窗冻结、
  C字节->Python还原、同LPF重放、插值边界、控制owner逐函数去除观察器后相等。

本轮编译初期扩展字段曾超过RAM16B，已仅合并等价的诊断滤波状态为LPF(Iq-friction)
并紧凑存储，最终链接通过；未缩减任何现有保护/heap/stack。
下一步先人工功率关闭核验候选启动/时序/堆栈，再考虑原安全边界下短窗采集。
尚未刷板，物理B975和停机状态未动。
