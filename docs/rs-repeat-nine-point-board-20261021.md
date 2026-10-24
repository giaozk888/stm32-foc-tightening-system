# Rs重复采集9段完成：全部数据对比，未正式资格化参数

用户明确授权50/75/100mA各3次整组采集，数据质量错误仍继续。
用户确认12V关闭、MCU供电、台架锁轴/外壳固定防护、原接线、12V限流0.5A，
并承诺整组期间现场立即断电；另行确认ON无报警后才执行。

## 执行方式与边界

- 固定计划为3轮，每轮50、75、100mA，各段最多400ms，共9段。
- 每段一个原固件one-shot命令，段后STOP/ANALOG SAFE、全Flash/RAM捕获并抓停。
- 下一段通过正常复位重新校准/原预检，绝不在同一boot中重新使能used命令。
- 首段仅一次原A/B试运行提交/正常确认；后8段复位已确认同一A，不重新刷写或操作B。
- 每段间有输出关闭/MCU停住和额外1秒间隔；无故障clear命令或未知ACK重发。
- 稳态/角度等数据质量失败继续记录。真实硬件/编码器/FOC deadline/CCR故障、
  输出关闭不明、未知ACK/传输/身份异常，或诊断motion/voltage/nonfinite退出则停止。
- 本次没有触发上述必须停止的条件，9段全部完成。
- 不运行速度环/位置环、不START拧紧、不自动进入Ld/Lq、不写参数或PI。

## 文件与检查

新host runner：`tools/motor_ident_rs_repeat_batch.py`。
`motor_identification_report.qualify_rs_point`只是把原单点质量检查抽成共享函数，
未改任何数值阈值、公式或固件。batch完整完成与全部质量通过使用独立字段。
新增6项batch测试，所有motor-ident相关84项通过。
测试包含九次全部QUALITY_FAILED仍全采、原75/100mA失败分类、真实保护立即停，
未知ACK不重发、files-only默认、三个独立点才可合格拟合等。

固件仍为`MotorParameterIdentificationRsRejectCountDiagnostic`，未改也未重刷：

- BIN SHA256 `19021c8c5e784fe4325c9fb8bb81177bc2e6189e150fd5832fc3a9337c8db4af`。
- ELF SHA256 `437dcaf5db263010313eb4b600bf60fb03d1350d804eb48655e1f140b26f6b46`。
- 原B BIN SHA256 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`未变。

stage `tmp/motor-ident-rs-repeat-stage-1792557862578763100.json`：
完整独立回读，programming=false，B/boot/private/metadata未变。
batch `tmp/motor-ident-rs-repeat-batch-1792557916637768800.json` COMPLETE：
completed_points9、safety_stop空、remaining_not_run空、all_quality_pass=false。
每段完整收据路径在parent.points，全部含当段Flash/RAM/串口/保护时序证据。

## 全部9段对比

这里“质量失败”不是保护故障。所有原始段保留，不把失败段变成成功。

| 顺序 | 档位/轮次 | mean Id mA | mean Iq mA | mean计算Vd mV | 首末mean Id差绝对值mA | 最大电角相对变化deg | 单段质量 |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | 50 / 1 | 48.509 | -8.582 | 36.255 | 3.893 | 0.879 | 通过 |
| 2 | 75 / 1 | 73.523 | -5.594 | 57.737 | 3.438 | 1.318 | 角度失败 |
| 3 | 100 / 1 | 102.078 | +14.156 | 80.233 | 9.240 | 1.318 | 角度失败 |
| 4 | 50 / 2 | 49.892 | +2.758 | 36.034 | 6.234 | 0.879 | 通过 |
| 5 | 75 / 2 | 75.434 | +4.666 | 54.877 | 2.152 | 1.099 | 角度失败 |
| 6 | 100 / 2 | 104.523 | +8.508 | 75.951 | 19.629 | 0.659 | 稳态失败 |
| 7 | 50 / 3 | 45.326 | -15.384 | 39.937 | 4.401 | 0.659 | 通过 |
| 8 | 75 / 3 | 75.408 | -1.499 | 59.874 | 1.396 | 1.099 | 角度失败 |
| 9 | 100 / 3 | 96.979 | -11.295 | 80.225 | 3.701 | 0.659 | 通过 |

每档三次均值与段间总体标准差（不是置信区间）：

| 档位 | mean Id mA | Id段均值std mA | mean计算Vd mV | Vd段均值std mV | 质量通过 |
|---|---:|---:|---:|---:|---:|
| 50mA | 47.909 | 1.912 | 37.409 | 1.790 | 3/3 |
| 75mA | 74.789 | 0.895 | 57.496 | 2.047 | 0/3 |
| 100mA | 101.193 | 3.143 | 78.803 | 2.017 | 1/3 |

重复数据说明均值趋势有一致性，但不能证明所有偏差已消除。
例如75mA三次mean Id较集中，然而三次角度检查均失败；
100mA第二次仍有19.629mA首末变化。角度变化可能为真实微动/顺应性/噪声，
没有额外物理证据不能唯一归因。没有修改原1electrical-deg/10mA质量判据。

## 拟合结果必须区分

### 原规则下的正式资格判定

4/9段合格，但75mA没有合格段，只有两个不同合格电流档位。
原fit_rs明确拒绝“缺少3个独立合格档位”，parent.comparison.qualified_rs=null。
Ld/Lq未测，PI/NVM未改。

### 含全部5段质量失败数据的参考趋势拟合

以下只作描述，**不是qualified Rs**，不接入控制或Ld/Lq自动流程。
来自全部9段平均Id/Vd和每档三次均值，均保留质量标签：

- 9个段均值拟合：斜率0.763267ohm，截距+0.939684mV，R²0.961936。
- 先按档位平均再拟合3点：斜率0.776772ohm，截距-0.068163mV，R²0.999509。
- 三轮各自参考斜率：0.820193、0.730525、0.772537ohm。

因此可说当前低电流命令电压—测量电流的**参考等效斜率约0.78ohm**，
但不能宣称绕组真实电阻已经标定为0.78ohm。
均值拟合高R²不消除角度/电流偏置、PWM死区等系统误差，也不证明角度假设成立。
不同聚合方式结果不同，禁止只挑最高R²掩盖个别段问题。
参考结果另存`tmp/rs-repeat-batch-descriptive-fit.json`，明确DESCRIPTIVE_UNQUALIFIED，
没有写回parent.qualified_rs或修改任何旧收据。

## 停机和恢复

用户确认整组结束后12V关闭，原bootloader流程恢复B并停入口，不执行B应用。
restore `tmp/motor-ident-rs-repeat-restore-1792558189146552900.json` COMPLETE/PASS：
确认B860、pending0，SD0、BDTR0、CCER0、CPU halted，B/boot/private/A字节未变。
全Flash SHA256 `9c574f068e64566d6b2a06af95231d4432534f9a505e28dfd6b723d41ace50aa`。

本轮到此结束，不再注入。
