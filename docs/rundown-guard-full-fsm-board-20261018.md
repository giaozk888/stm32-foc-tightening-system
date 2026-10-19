# 修复起转门控后的原状态机实机验证

## 结果

**假 CONTACT 门控验证通过；20rpm速度跟踪和完整拧紧流程未通过。**
通过原START入口只发送一次请求7830，没有自动重试，没有绕过门控进入电流段。
本轮空载固定，不是真实带工件拧紧或扭矩精度验收。

板端RUNDOWN持续2770ms，以 `NO_ROTATION`（outcome7、state11）停止：
`rundown_armed=0`、`contact_confirmed=0`、`foc_fault=0`，未返回OK。
只观察到阶段1→11，未进入CONTACT_STOP及后续电流/保持阶段。
这说明修复后的状态机阻止了先前“没正常起转也走完整流程”的漏洞；
不代表物理起转不足的问题已经解决。

## 操作与证据身份

用户确认12V关闭，随后确认开启（0.5A、无报警、可立即断电）。
用户明确要求使用修复后的完整状态机；未用2秒host STOP截断。
沿用板端12秒独立租约、原20rpm准入和全部保护。仅临时把RAM中
RUNDOWN_RPM从70设为20，结束后恢复70，没有SAVE或其他参数修改。

- 暂存：`tmp/rundown-guard-stage-1792323398614316700.json`。
- 首次预检：`tmp/rundown-guard-run-1792323719565462200.json`。
- 唯一实际START：`tmp/rundown-guard-run-1792328175608650600.json`。
- 匹配的Flash/SRAM位于上述运行收据的final_capture/ram_capture，忽略目录不公开。
- A preset：`RundownDiagnosticTrial`，228220B。
- BIN SHA：`a9c5cf73e0d32540d90557d2c3f69ec7cfbd8ff94939261741bfc21604636234`。
- ELF SHA：`ba82c420a645d99adcb32c83b18cf37cad0de3ce0a092c2d2f162131818175a9`。

首次运行已经正常健康确认A668，但未发START：主机Console只读allowlist
不支持新增的 `MOTOR TEST STARTUP CONFIG` 查询，抛出异常后立即关闭输出、
停住MCU并保存快照；没有电机故障。只修脚本：依据精确BIN/ELF/完整Flash
绑定schema，不再发这个多余查询。新增严格pre-start恢复入口：必须核对
旧收据start_attempts=0、未有START命令、已确认A、未有首故障、应用/私有区
未变化，才允许复位同一镜像，不重刷、不再提交trial元数据。
不能将这种“确认没有START的脚本预检恢复”套用于运动失败重试。

用户之后要求继续，复位当前A668预检后才发送唯一一次START。
脚本10项测试PASS，补充pre-start恢复身份/模糊START拒绝测试后11项PASS。
没有修改已上板的固件、PI、控制算法、相序、保护或状态机门槛。

## 零点、时序、保护

| 项目 | 本次实际START会话 |
|---|---:|
| zero valid/reject/total |4000 /38 /4040|
| zero max consecutive reject |1|
| zero U/V |1561 /1564|
| 预检wall max |27.17µs|
| 预检actual margin min |15.458µs|
| 会话FOC wall max |28.8353µs|
| deadline miss |0|
| actual CCR commit |192949|
| actual CCR late |0|
| actual margin min |5.3647µs|
| CUR_CONFIRM enter/clear/fault |70 /70 /0|
| current unresolved max consecutive |1|
| stop snapshot domain/reason |PROCESS /NO_ROTATION(7)|

更新余量仍正且大于原1µs guard，但由约15µs下降到5.36µs，不能沿用旧版
15µs作为新诊断版最坏余量。短临界区快照可能影响入口调度，但本次没有
同周期证据将这个最小值唯一归因于快照，不能直接改warning或调NVIC。

## 起转与NO_ROTATION演化

| host首次观察/s | 速度CTRL/rpm | IqRef/mA | 状态 |
|---:|---:|---:|---|
|0.078|0.3|36|RUNDOWN，CONTACT=0|
|0.697|0.8|300|仍RUNDOWN，未armed|
|0.948|0.8|约400|仍RUNDOWN，不再误判CONTACT|
|约1.3|出现短促运动/制动|需求随后下降并反向|仍未连续满足起转建立条件|
|1.735|6.4|−22|检测速度21.6rpm，但控制速度未同步持续合格|
|2.769|1.5|386|再次持续高需求，仍未armed|
|2.868|−9.8|0|NO_ROTATION，CONTACT=0，IDLE|

NO_ROTATION不是无条件1500ms强停：还要求持续250ms的高同向Iq需求。
本次约1.3s短促运动触发原SB3减驱/制动，需求下降，重置高需求候选。
最终guard记录 `drive_ms=2520`、`last_ms=2770`，正好持续250ms，
且elapsed≥1500ms，因此2770ms判NO_ROTATION符合已实现逻辑。
`motion_ms=1690`只代表某次候选开始，不是armed；终态motion_candidate=0。

串口50–70ms稀疏STATUS中的CTRL峰值9.6rpm；32帧任务侧启动记录捕获到
16.976rpm，instant峰值43.989rpm。两者采样相位不同，不是矛盾：存在短峰，
不是稳定达到20rpm，也不能把9.6或16.98当作整个过程中真正最大值。

## 新窗口提供的物理线索

32帧从0.935ms覆盖到1571.969ms，保留启动而非末尾HOLD；另有2771.346ms
post-stop终止帧。后者IqRef已归零，不能用来代表停机前的驱动需求。

在12个IqRef≥0.30A的保留帧中：

- IqRef平均0.38160A，板端Iq平均0.39935A；平均绝对误差约44.10mA。
- 全32帧Vdq矢量最大0.20011V，电压饱和标志0/32，远低于1.6V。
- Id绝对值最大0.11563A，部分瞬间偏离明显，不是完全理想的Iq跟踪。
- 约1318.937ms：IqRef−74.91mA、Iq+161.84mA，换向时电流存在滞后。
  随后1368.967ms已为−23.76/−23.03mA；不能仅凭单点反号认定反馈极性反了。
- 编码器32帧valid均1、glitch streak均0，accepted dt范围984–1002µs。
  由保存delta/dt重算的instant与记录差值最大0.00365rpm（dt整数化误差）。
- 最初到1572ms机械累计角约0.088→8.899°；是小幅/断续运动，不是完全没动。

这些证据优先排除了“本次始终因为1.6V上限饱和而不起转”的解释，也不支持
“Iq始终明显不足”作为唯一原因。更接近“软件dq电流有响应，但机械运动/转矩
转换不稳定”的调查分支。仍不能单凭同一ADC/角度模型独立证明电流映射、
物理相电流、相序/电角零点和真实桥端输出正确；机械阻力、角度/相位对应、
死区/桥执行及采样准确性尚不能唯一判定。未自动修改任何相序、符号或PI。
20Hz记录不能排除更短的尖峰；encoder数据自洽也不是独立转速计验收。

### 诊断字段缺陷（未在本轮重刷）

扩展frame的 `actual_commit_count` 读取 `foc_pwm_write_profile.writes`，
但LIGHT构建只维护 `.points`，因此该逐帧字段为0，**不表示没写CCR**。
最终timing解码正确使用 `.points`，本会话实际提交192949次，late=0。
pending CCR与寄存器preload读回有记录，但仍不能证明功率桥实际输出。
本轮保留原镜像身份，没有为了补这个诊断字段重刷/重跑。

## 停止与最终边界

状态机自身NO_ROTATION停机后，host执行STOP/ANALOG SAFE，核验
SD=0、MOE=0、FOC=0；恢复RAM配方70rpm，保存Flash/SRAM并停住MCU。
bootloader、B槽及私有配置与运行前逐字节一致；A668已正常确认，pendingnone。
用户确认12V关闭后，已通过原bootloader mailbox恢复B启动选择并回读通过：
`tmp/rundown-guard-restore-1792328374450150600.json`，generation669，
confirmedB、pendingnone、attempts0。硬件断点停在B应用入口前，B未运行。
最终VTOR=0x08040000、SD=0、BDTR=0、CCER=0、MCUhalted；应用镜像、
bootloader和私有配置与恢复前逐字节一致，仅启动元数据按正常流程更新。
不再次START，不把本轮NO_ROTATION当作完整状态机或速度验收PASS。
