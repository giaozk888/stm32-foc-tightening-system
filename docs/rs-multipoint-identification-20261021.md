# Rs 50/75/100mA三点采集：暂不能资格化参数

用户要求参数辨识。已复用50mA有效采集，本轮另行人工确认并执行75mA和100mA各一次，
都为Id固定/Iq0、台架锁轴、12V/0.5A、最多400ms；没有自动重试、连续升档或Ld/Lq。
每次OFF复核/准备、另行ON无报警确认、采完关输出抓停、人工OFF后恢复B。
75mA稳态问题在100mA前已明确告知，100mA仅作人工授权的独立对照。

## 镜像和脚本

固件仍为`MotorParameterIdentificationRsRejectCountDiagnostic`，本轮不改固件、不重复写Flash。
BIN SHA256 `19021c8c5e784fe4325c9fb8bb81177bc2e6189e150fd5832fc3a9337c8db4af`。
ELF SHA256 `437dcaf5db263010313eb4b600bf60fb03d1350d804eb48655e1f140b26f6b46`。

新增两个独立精确runner：

- `tools/motor_ident_rs75_board.py`：B848基线，只允许一次RS75。
- `tools/motor_ident_rs100_point_board.py`：B852基线，只允许一次RS100。

复用原one-shot命令、原预检/独立保护/关断和完整Flash/RAM捕获流程。
共享runner的档位、命令、收据名前缀和test.id_ref一致，不把75/100mA标成50mA。
档位仅支持已存在的50/75/100，缺少匹配命令即拒绝；解码核验实际current_a。
默认运行仍files-only，不接设备。没有新增自动网格/下一点。
新增各3项脚本测试，最终motor-ident相关78项通过。

## 收据

50mA原run：`tmp/motor-ident-rs50-run-1792556483256768500.json`。

75mA：

- stage `tmp/motor-ident-rs75-stage-1792556778917051000.json` PASS，programming=false。
- run `tmp/motor-ident-rs75-run-1792556826437979800.json`：完整32行采集PASS。
- restore `tmp/motor-ident-rs75-restore-1792556906074918500.json` PASS，恢复B852并停入口。

100mA：

- stage `tmp/motor-ident-rs100-stage-1792557010207567400.json` PASS，programming=false。
- run `tmp/motor-ident-rs100-run-1792557053888043300.json`：固件DONE/32行/REASON0，
  主机静止质量门限失败，整体STOPPED/FAIL；没有把质量失败改写成辨识成功。
- restore `tmp/motor-ident-rs100-restore-1792557122933125000.json` PASS。

## 数据与资格判定

| IdRef | mean Id | mean Iq | mean计算Vd | 前后8点mean Id差绝对值 | 最大电角相对变化 | 判定 |
|---|---:|---:|---:|---:|---:|---|
| 50mA | 49.390mA | +3.121mA | 40.221mV | 2.825mA | 0.879deg | 单点质量通过 |
| 75mA | 73.728mA | -4.578mA | 53.575mV | 10.122mA | 0.659deg | 未通过原10mA稳态要求 |
| 100mA | 95.332mA | -8.489mA | 75.969mV | 0.932mA | 1.099deg | 未通过原1electrical-deg静止要求 |

75mA首8点mean Id75.428mA，尾8点65.306mA；差10.122mA。
这只是软件依据分段均值判断未稳态，不能仅据它断言电机电阻发生变化；
也可能是小窗口噪声。没有因只超0.122mA就自动放宽原规则。

100mA角度变化是编码器反馈值，不等于已证明轴真实松动：
可能是实际微动、夹具顺应性或测量噪声，现数据不足以唯一归因。
没有改electrical zero、相序、encoder direction或噪声/稳态门限。

三次Id标准差分别15.111/16.978/19.983mA，仍有明显测量波动。
不能把单点Vd/Id或对不合格三点强行直线拟合的数值当作正式Rs。
原拟合程序对50mA单点先通过质量检查，随后明确拒绝“不足3个点”；
对50+75mA在稳态检查处拒绝；100mA在angle guard处拒绝。
结果：Rs未资格化，Ld/Lq未开展，PI建议未生成或写入。

汇总原始数值见`tmp/rs-multipoint-summary.json`；
拟合门限输出见`tmp/rs50-pre-multipoint-quality.log`、`tmp/rs50-rs75-quality.log`。

## 时序/保护

| IdRef | FOC wall max | deadline miss | actual CCR late | min actual margin |
|---|---:|---:|---:|---:|
| 50mA | 36.200us | 0 | 0 | 15.112us |
| 75mA | 36.694us | 0 | 0 | 14.582us |
| 100mA | 36.524us | 0 | 0 | 14.041us |

75/100mA均无原保护故障；坏样本仅排除，不参与估计：
reject184/180、good7784/7788、max consecutive2/2，explained gap34/34。
本轮不再修改准入、算法或保护门限以强行给出参数。

## 最终状态

用户确认12V关闭后，恢复原B并停在入口，不运行B应用。
原B/boot/private和候选A字节保留，SD/MOE/CCER关闭、MCU halted。
若要完成辨识，后续需针对75mA稳定性和100mA角度变化复核/安排重采，
不能直接进入依赖合格Rs的Ld/Lq步骤。本轮到此停止。
