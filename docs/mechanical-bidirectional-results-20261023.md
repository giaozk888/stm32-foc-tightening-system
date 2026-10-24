# 正反向九轮联合辨识结果（DOB归一化候选）

## 实际运行与来源

人工确认反向机械许可、12V关闭、MCU供电、空载固定/防护/接线及0.5A限流不变后，仅写非活动A。收据 `tmp/mechanical-ident-stage-1792713171888168400.json` 两次完整回读PASS，原B/boot/config未变。用户随后另行确认已上电、无报警且全程可立即断电，才执行负向九轮。

- 正向：`tmp/mechanical-ident-batch-1792675998078677600.json`，600/700/800rpm各3次。
- 正向ELF：`foc2_app_a/build/MechanicalReadinessSnapshotCandidate/foc2.elf`。
- 反向：`tmp/mechanical-ident-batch-1792713255600021200.json`，-600/-700/-800rpm各3次，**9/9 PASS**。
- 反向ELF：`foc2_app_a/build/MechanicalReverseIdentificationCandidate/foc2.elf`，BIN SHA `cad191865cadd1e8dc8377f79e36341170e07c414b8b7defbb4c4d4e40d8f57d`，ELF SHA `8fddaa5264301f04428c413970609318b72f06cefa414f494b4d608b5aac47dc`。
- 完整联合分析：`tmp/mechanical-bidirectional-fit-1792713255600021200.json`；不是仅使用子收据里缓存的已解码数组，CLI重新验证18组匹配BIN/ELF/Flash/RAM及独立会话、保护/关断来源。
- 最后一轮：`tmp/mechanical-ident-run-1792713517791586500.json`。全部子收据路径列于各批次的runs字段。

两种编译profile的唯一define差异是反向命令白名单。控制参数一致：Ka=0.000046875 A/(rpm/s)、friction=0.105A、BEMF ψ=0.00034866Wb、Iq±0.50A、电压1.60V、超速1000rpm、行程30000°、驱动5s和原减速/lease/时序保护。不增加DOB执行、不调PI或改符号，无自动重试。

## 反向稳态速度、电流

与正向采用相同固定窗口、只取完整无flag64ms bin，dt加权后对三轮取均值。600/700/800档窗口分别3.65~4.95、4.15~4.95、4.65~4.95s；800档稳态实际完整bin仅0.192~0.256s，不代表长时间耐久。

|目标rpm|第一次rpm / Iq A|第二次rpm / Iq A|第三次rpm / Iq A|三次平均rpm|平均Iq A|
|---|---|---|---|---:|---:|
|-600|-599.2317 / -0.217749|-597.9498 / -0.219180|-598.8236 / -0.219657|-598.6684|-0.218862|
|-700|-699.7751 / -0.229767|-695.7882 / -0.232329|-698.6646 / -0.233931|-698.0759|-0.232009|
|-800|-798.3014 / -0.240619|-794.3999 / -0.247842|-797.4417 / -0.242583|-796.7143|-0.243682|

- 九轮均无first fault，无encoder timeout/DMA error/schedule miss/control stale；NOT_READY=0、每轮仅一个RUN，无重试。
- FOC最大wall time33.694118µs，deadline miss=0、CCR late=0、最小实际CCR余量12.911765µs。
- 实际最后准入ADC age依次41、42、32、41、42、43、39、27、42µs，failed=0，reject.valid=0，原100µs门限不变。
- CUR_CONFIRM各轮enter/clear/fault：124/124/0、145/145/0、134/134/0、143/143/0、152/152/0、165/165/0、162/162/0、160/160/0、147/147/0。
- outer trace最大task entry gap1099µs、core192µs、非控制观察143µs；这些是包含IRQ抢占和预检的不同最大值，不相加冒充单次耗时。

## 分方向拟合：验证对称性，不能取Iq绝对值

`Iq = a*alpha + b*omega + c_direction`，omega/alpha均为有符号机械rad/s、rad/s²。

|参数|正向独立拟合|反向独立拟合|
|---|---:|---:|
|J/Kt [A·s²/rad]|0.0003860492189|0.0003691530682|
|B/Kt [A·s/rad]|0.001551576508|0.001584255907|
|方向截距 [A]|+0.1207347546|-0.1181354203|
|有效窗口|975|981|
|R²|0.9238994660|0.9395432364|
|残差RMS [A]|0.0095445805|0.0085974915|

J/Kt正反向相对差异4.37668%，B/Kt差异2.06276%，通过现有30%分析一致性准则（非保护阈值）。按这两个**独立斜率**的截距直接计算，诊断结果为Ic=0.1194350874A、bias=0.0012996671A；因为两个方向a/b并不完全相同，这不作为共同模型最终标定。

## 推荐联合候选：共同J/Kt、B/Kt下分离Ic与bias

同时拟合：

`Iq = (J/Kt)*alpha + (B/Kt)*omega + Ic*sign(omega) + bias`

|字段|联合64ms主窗口|128ms复核|
|---|---:|---:|
|J/Kt [A·s²/rad]|**0.0003782906587**|0.0003728295779|
|B/Kt [A·s/rad]|**0.001567686433**|0.001589204859|
|Ic：库仑摩擦等效电流 [A]|**0.1194516824**|0.1184578233|
|bias：模型电流偏置 [A]|**0.0005496600**|0.0005159073|
|有效窗口|1956|909|
|R²|0.9978200276|0.9987238871|
|残差RMS [A]|0.0090904646|0.0068867353|

共同模型的c+=0.1200013424A、c-=-0.1189020223A，所以仍严格满足 `Ic=(c+-c-)/2`、`bias=(c++c-)/2`。不要混用“独立方向斜率的截距”和“共同斜率的截距”求出两个不同bias后当成矛盾。

J/Kt随窗口加倍变化-1.443620%，18个leave-one-session-out全部通过，normalized_bidirectional_qualified=true，problems=[]。全体带符号样本用独立四列加权QR再次验证，与原缩放正规方程解一致到1e-11以内。联合R²受到正负方向电流跨度增大影响，因此同时报告较低的分方向R²和残差，不单凭0.99782断言动态完美。

上述bias是“对称Coulomb＋方向无关常量项”模型下的估计，可能包含非对称负载/摩擦及电流测量偏置，**不是独立测出的ADC零点误差**。最低有效速度约20rpm，零速/静摩擦区域和不同负载下不能直接外推。

## DOB候选与未做的事

分析JSON已保存直接对应现有 `MechanicalNormalizedModel` 的candidate_dob_shadow_model：以上共同a/b/Ic/bias，bandwidth_rad_s=12.56637061（2Hz）、min_speed_rad_s=2.09439510（20rpm）、qualified=1。这里qualified仅表示离线模型质量合格，不等于已批准或启用DOB闭环。

用本次实际拟合值再次编译/执行原C `MechanicalDob_Observe` 接口，正/负方向的合成±0.02A扰动和fault失效检查PASS。这是**纯离线观察接口验证，不是板端DOB验证**，没有把64ms bin伪装成1kHz原始记录。

参数仍只保存在候选分析结果：未自动改现用Ka、friction、PI，不写B，不加载板端DOB，不反馈到Iq。Kt未独立标定，absolute_parameters=null，不输出伪标定的绝对J/B/Kt或Nm扰动。

## 停机/恢复状态

反向九轮最后输出关闭、MCU停住。用户明确回复“关了，按照图继续下一步”后，仅恢复原B启动选择：`tmp/mechanical-ident-restore-1792713878339933000.json` PASS，原B/boot/config/private未变、B application not run=true、motor_commands=0；最终VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted。后续只准备DOB观察候选，不自动运行或启用补偿。
