# Rs拒绝只统计候选：50mA单点完整采集

## 范围与流程

用户确认12V关闭/MCU供电、台架锁轴/外壳固定防护、原接线、12V限流0.5A及
现场立即断电条件；仅写非活动A，保留B；完整回读后另行确认ON无报警。
恰好执行一次IdRef50mA/IqRef0、最多400ms的Rs采集。
无START、无自动重试、无75/100mA/Ld/Lq后续注入。

- preset `MotorParameterIdentificationRsRejectCountDiagnostic`，BIN215132B。
- BIN SHA256 `19021c8c5e784fe4325c9fb8bb81177bc2e6189e150fd5832fc3a9337c8db4af`。
- ELF SHA256 `437dcaf5db263010313eb4b600bf60fb03d1350d804eb48655e1f140b26f6b46`。
- 新runner `tools/motor_ident_rs_reject_count_board.py`，精确B844基线/ABI1740B。
- decoder增加显式run_reject_stop=False opt-in，默认仍按旧连续3对规则；
  前台日志要求RUN_STOP0/RUN_LIMIT0/RUN_SAT255，且保留gap/时间/原保护核验。
- 新脚本3项检查、全部motor-ident相关合计72项通过。
- stage `tmp/motor-ident-rs50-stage-1792556439866324700.json` PASS：
  完整独立回读，B/boot/private/metadata未变，未激活、输出关闭。
- run `tmp/motor-ident-rs50-run-1792556483256768500.json` PASS。

## 本次结果

正常health5秒确认/复位、零点、时序和栈预检均通过。
RS50明确ACK，最终STATUS3/DONE、REASON0、N32，原保护/timing同会话证据通过。
400ms固定截止正常结束；最后有效参考相对start399969us，
记录窗口200016..395270us，共32行，没有延长测试以等样本。

| 采集结果 | 值 |
|---|---:|
| 平均Id | 0.049390375A |
| 平均Iq | 0.003120634A |
| 平均计算Vd | 0.040221428V |
| 单点Vd/Id观察值 | 0.814357605ohm |
| Id标准差 | 0.015111374A |
| Iq标准差 | 0.033101370A |
| 有效32行最大abs(Id)/abs(Iq) | 0.10943944 / 0.13426924A |
| 有效32行最大abs(speed) | 0.570197rpm |
| 最大相对首行电角偏移 | 0.878854electrical deg |
| reject / good / max consecutive reject | 165 / 7810 / 1 |
| reject占比 | 约2.069% |
| explained gap events / skipped / max gap | 27 / 27 / 1 |

165对被排除的current sample未混入32行估计窗口。
本次MAX_RUN1，所以实机没有覆盖连续reject>=3；该新逻辑的边界验证来自离线C测试。
本次实际超过旧16次gap预算，读回BUDGET0/TOTAL_STOP0并完整结束。

成功采集不代表噪声消失，Id/Iq仍有明显波动。
0.814ohm只是**计算Vd命令/测得Id的单点比值**，不是已拟合资格化的绕组Rs。
尤其低电压下可能包含逆变器非理想偏置，不能据一个点自动改PI。
最终Rs需独立确认的50/75/100mA至少3个点通过原稳态/跟踪/噪声/电压偏置拟合要求。
本轮没有计算Ld/Lq、没有写PI/正式参数/NVM。

## 时序与原保护

- FOC wall max36.20us，deadline miss0。
- actual CCR commits141631，late0，min margin15.11176us。
- cl_flags/cl_fault_valid/adc_fault/foc_fault均0，encoder_valid1。
- CUR_CONFIRM66enter/66clear/0fault，max2cycles/100us。
- encoder attempts6932/successes6932/failures0，max transaction249us。
- encoder timeout/DMA error/schedule miss/control stale均0。
- encoder慢计数0->204，包含前后命令及停止后读出，不能冒充纯400ms窗口次数。

## OFF/恢复

输出关闭、MCU抓停后，用户确认12V关闭。
仅恢复原B启动选择并停在入口，没有执行B应用、没有再次注入。
restore `tmp/motor-ident-rs50-restore-1792556545056346300.json` PASS。
B/boot/private及A镜像字节保留，SD/MOE/CCER关闭、CPU halted。

后续任何下一电流点都需另行人工安排，本轮到此停止。
