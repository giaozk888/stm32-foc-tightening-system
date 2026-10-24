# 正反向机械辨识 → 摩擦/偏置分离 → 电流归一化 DOB

按用户截图实施。此阶段只准备独立A候选、离线分析和观察接口验证；没有刷板、复位、启动或更改B。正向来源为已恢复B的九轮600/700/800rpm采集；真实反向数据尚未采集，不能宣称新的Ic或bias已测出。

## 反向候选

`MechanicalReverseIdentificationCandidate` 继承当前已验证的 `MechanicalReadinessSnapshotCandidate`，仅新增默认OFF的 `FOC_MECHANICAL_REVERSE_IDENT_DIAG`。

- 只接受显式 `MOTOR TEST MECH RUN NEG 600/700/800`，返回带符号的-600/-700/-800；拒绝POS、其他速度、负号重复、后缀字符和START。不是自动反转正常拧紧流程。
- 新只读 `MOTOR TEST MECH DIRECTION` 必须返回 `REVERSE_IDENT=1 SIGN=-1 GRID_RPM=600,700,800 DOB_CONTROL=0`。
- 原硬件功率使能、校准、准入、100µs样本新鲜度、NO_ROTATION、双通道保护、CUR_CONFIRM、CURRENT_INVALID、2ms/2.5ms看门狗及停止路径均不变。
- 与正向完全相同：Ka=0.000046875 A/(rpm/s)、friction=0.105A、BEMF ψ=0.00034866Wb、Iq限幅±0.50A、电压1.60V、超速1000rpm、行程30000°、S-curve200rpm/s及1000rpm/s²、驱动5s、减速闭合10.5s、独立lease12s。
- 原control encoder direction、Park/Clarke、相序、电角零点、PI及IRQ不变。负向是原速度目标的负号，不通过交换相序或改编码器方向实现。

新A BIN209744B、RAM129544/131008B，静态余量1464B，未缩heap或线程栈。

- BIN SHA256 `cad191865cadd1e8dc8377f79e36341170e07c414b8b7defbb4c4d4e40d8f57d`。
- ELF SHA256 `8fddaa5264301f04428c413970609318b72f06cefa414f494b4d608b5aac47dc`。
- B增量构建通过，BIN SHA256仍 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`；原已测正向A镜像未覆盖。
- main编译warning集合与正向候选一致，无新增warning；保留既有unused/RWX warning。

## 批次准备（未执行）

`tools/mechanical_reverse_batch.py` 默认只检查文件，不访问设备。固定-600/-700/-800rpm各3次，共9轮，各轮保持原5s速度命令和原减速关断。不自动升流、不自动重试，不提高任何保护。

脚本先以原身份验证实际B恢复收据 `tmp/mechanical-ident-restore-1792679166747314300.json`，再安装新镜像身份；不能复用正向stage收据。每轮RUN前同时核验反向专用identity和readiness FIX=1，拒绝错误镜像。保护、未知ACK或关断证据失败则停止整批；质量拟合差保留数据，不自动写入模型。

准备前必须确认12V关闭、MCU供电、转轴解锁且电机空载固定有防护，接线不变、电源限流0.5A，机械/联轴器/附件允许反向800rpm，操作者能全程立即断电。反向可能松动螺纹连接，不沿用此前仅正向的机械许可。上电后另行确认无报警，采完关断确认后只恢复原B。

## 正反向参数分离

离线工具 `tools/mechanical_bidirectional_fit.py`：

```
Iq = a*alpha + b*omega + Ic*sign(omega) + bias
a = J/Kt
b = B/Kt
c+ = Ic + bias
c- = -Ic + bias
Ic = (c+ - c-)/2
bias = (c+ + c-)/2
```

所有Iq、机械omega[rad/s]和alpha[rad/s²]保留真实符号；c-通常为负，不能先取绝对值。先分别以有符号三列加权QR拟合正负方向的a/b/c，再联合四列拟合共同的a/b/Ic/bias；独立方向截距用于诊断，最终候选来自合格的共同模型，不通过简单平均掩盖方向差异。

准入复用原固定64ms窗口/128ms复核、Id接近零、无饱和/无质量flag、异常后两窗恢复等条件；不按残差删点、不人为改符号、不拟合时间平移。额外分析检查：正负方向各≥3个独立会话，a/b相对差异≤30%（复用原模型敏感度容限，**不是保护阈值**），真实方向与指令一致；原残差RMS≤0.03A、R²≥0.7、窗口敏感度≤30%、留一会话检查和来源/关断检查保持。

输入必须是两个完整9轮批次和各自匹配ELF，逐轮重新验证BIN/ELF/Flash/RAM哈希、独立会话、保护及关断证据。编译参数允许的唯一差异是反向命令开关；Ka、FF、friction、BEMF及限幅不一致就拒绝合并。

当前正向来源：

- 批次 `tmp/mechanical-ident-batch-1792675998078677600.json`。
- ELF `foc2_app_a/build/MechanicalReadinessSnapshotCandidate/foc2.elf`。
- 先前已确认 a=0.0003860492189、b=0.001551576508、c+=0.1207347546A。
- c-尚未知，所以此时Ic/bias仍未知；不把c+全赋给Ic、不擅自假设bias=0。

对称Coulomb＋方向无关常量偏置是模型假设，不是绝对物理证明。方向相关负载/摩擦不对称可能伪装为“电流bias”；报告保留方向差异和这一限制，不能把统计截距直接宣称为独立测出的ADC零偏。

## DOB接口及资格

不需要先知道绝对Kt。只有双向联合模型全部通过时，输出 `candidate_dob_shadow_model`，字段直接对应现有 `MechanicalNormalizedModel`：

`j_over_kt, b_over_kt, coulomb_over_kt, bias_a, bandwidth_rad_s, min_speed_rad_s, qualified`。

观察候选带宽2Hz（12.56637rad/s）、最低速度20rpm对应2.094395rad/s；这不是调PI或改保护门限。

现有观察接口公式：

`d_hat_A = Q(s)[Iq - b*omega - Ic*sign(omega) - bias] - a*s*Q(s)*omega`

已用拟合生成的合格模型在原C `MechanicalDob_Observe` 接口上验证正/负方向及故障/未配置失效。该接口不写Iq/PI/PWM，不反馈到控制器。**本轮没有把DOB观察器挂入板端1kHz路径，更没有启用DOB闭环补偿**；真实反向辨识完成后，先审核模型，再准备实际同步观察窗口，不把64ms离线bin伪称为1kHz DOB实测。

只有正向、方向差异大、残差/敏感度差、来源或保护不通过时，`candidate_dob_shadow_model=null`。绝对J/B/Kt保持未知，Nm扰动输出保持未标定，parameter_writes=false、dob_control_enabled=false。

## 修改文件及专项验证

- `firmware_common/friction_calibration.h`：独立负向白名单。
- `firmware_common/friction_calibration_binding.inc`：反向只读身份。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：A-only默认OFF预设。
- `tools/readiness_snapshot_batch.py`：允许显式匹配ELF解码；旧默认不变。
- `tools/mechanical_reverse_batch.py`：固定九轮反向批次准备，默认无设备访问。
- `tools/mechanical_bidirectional_fit.py`：双向来源核验、摩擦/bias分离、候选DOB模型资格。
- `firmware_common/mechanical_dob_shadow.h`：仅补充参数语义注释，观察算法未变。
- `tests/test_mechanical_reverse_candidate.py`、`tests/test_mechanical_bidirectional_fit.py`：负向命令、guard、控制/IRQ对象冻结、构建身份、方向不对称、拟合恢复、错误来源及参数到观察接口验证。

反向专项6项、双向拟合专项5项已通过；-Os/-O2原生C运行覆盖负向起转/不转/错误方向、正反扰动观察及fault失效。完整相关回归结果另见 `tmp/mechanical-reverse-regressions.log`。

最终相关离线回归 **233项全部通过**，耗时106.869s；包含既有encoder、outer、protected loop、mechanical、speed、dq/BEMF、PWM、FSM及新反向/双向专项。不是宣称其他仓库项目全部测试已执行。A/B构建通过，未新增warning，未进行任何板端刷写或运动。

## 后续人工板测：已断电暂存，尚未运动

用户随后要求板测，并确认12V关闭、MCU供电、空载固定防护/接线及0.5A限流不变、机械允许反向800rpm且可全程立即断电。

`tmp/mechanical-ident-stage-1792713171888168400.json` PASS：仅非活动A写入，两次完整回读通过；原B/boot/private/config未变，activation=false、motor_commands=0、SD/BDTR/CCER=0、CPU halted。新镜像BIN/ELF身份与上文一致。随后只提示用户开启12V并确认无报警及全程可立即断电；此条暂存记录不代表反向九轮已经执行。

用户随后明确确认上电条件，反向九轮已实际完成：`tmp/mechanical-ident-batch-1792713255600021200.json` PASS，无NOT_READY/保护/CCR late/deadline miss。与已有正向九轮的联合分析通过，结果见 `docs/mechanical-bidirectional-results-20261023.md`。尚未应用参数或启用板端DOB补偿。
