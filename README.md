# STM32 FOC 拧紧系统与多设备通信

基于 STM32G474、FreeRTOS 和 C/C++ 的电机控制实验项目，包含 A/B IAP、Pigweed 通信、ESP32 网关、鲁班猫上位机及主机测试工具。

这是开发与实验仓库，不是已通过工业认证的产品。历史记录中的离线通过、功率关闭计算、桥开关测试和电机闭环测试是不同验收范围，不能相互替代；没有扭矩仪的模拟测试不能证明真实扭矩精度。

2026-10-23：按人工选择，正常 A 构建改用 `TighteningDob025`，DOB 增益固定 `0.25`。
启动后需通过原电流质量门控和观察器预热才补偿；补偿上限仍为 `min(0.025 A, 5% × Iq_limit)`，
与 PI／加速度前馈／摩擦补偿统一限幅及 anti-windup。STOP／故障清零，不自动启动。
保留原 START 单次准入及全部保护，未改板上 B、未刷板；这是正式选用的软件配置，不等同于负载扰动验收。
详见 [DOB 0.25 正常流程接入](docs/dob025-normal-control-20261023.md)。下列条目保留历史版本范围。

另按用户选择准备独立A预设 `TighteningDob025Contact20Observe10Candidate`：
CONTACT<=20rpm、DOB观察下限10rpm，新鲜反馈速度准入仍20rpm，其他流程／
保护不变；只改候选RAM配方，不覆盖原正式选用镜像或B，尚未刷板。
详见 [CONTACT20／DOB观察10候选](docs/dob-contact20-observe10-candidate-20261023.md)。

2026-10-22 最新候选选择：BEMF ψf=`0.00034866 Wb`，Ka=`0.000046875 A/(rpm/s)`，后续不再用倍数代替 Ka 数值。
正常 A 预设为 `TighteningBemfHalfCandidate`，另提供被动采集的 `MechanicalIdentificationCandidate`。
机械辨识先输出 J/Kt、B/Kt 等比例参数；DOB 只准备旁路模型接口，不参与控制，不能把调节后的 BEMF 系数当成已标定物理 Kt。
详见[机械辨识与 DOB 候选说明](docs/mechanical-identification-dob-candidate-20261022.md)。本轮只完成软件准备，未刷板、未启动、未修改正式 B。

2026-10-22：按人工选择，将0.25倍Ka（`0.000046875 A/(rpm/s)`）固定到正常A预设
`TighteningKa025Candidate`，不带Ka辨识/增益扫描诊断；BEMF默认OFF，另提供
`TighteningKa025BemfOnCandidate`用于既有反电动势前馈验证。两者采用ψf=`0.00069732 Wb`，
正式B和历史镜像不替换。详见[Ka025正常A与BEMF对照准备](docs/ka025-normal-bemf-candidate-20261022.md)。
这是正常运行候选配置，不表示已刷板、已通过该组合板测或已修改B。

新增单独 A 的 [240 rpm（4 转/秒）候选配置](docs/rundown240-candidate-20261019.md)：超速边界 300 rpm，速度模式 Iq 上限按后续请求设为 ±0.50 A，原 PI 参数与其他保护不变；配方仅改 RAM、禁止 SAVE。[一次人工空载短测](docs/rundown240-500ma-board-20261019.md)已建立运动，观察最高 228.7 rpm，但尾段平均 204.13 rpm，稳速未通过；FOC max=31.40 µs、deadline/CCR late=0。测试已停机，不是完整拧紧验收。

后续[状态机自然结束实测](docs/rundown240-fsm-board-20261020.md)未按两秒提前停止：约 3.47 秒达到原 3000° 行程上限，现有逻辑统一报告 RUNDOWN_TIMEOUT；无 CONTACT/OK，观察最高 231.4 rpm、FOC max=31.641 µs、deadline/CCR late=0。已断 12 V 并恢复原 B741，未宣称空载完成真实拧紧。

随后按用户请求准备单独 A 的 [20000° 行程候选](docs/travel20000-candidate-20261020.md)，240 rpm、±0.50 A、300 rpm 超速及原 8 秒超时保持不变。编译、46 项定向回归与 3 项配方 CTest 通过；非活动 A 已暂存并独立回读，尚未激活或启动，B741/配置保留。

该候选的[一次启动尝试](docs/travel20000-preflight-abort-20261020.md)在功率关闭的 5 秒健康窗内触发 CURRENT_INVALID（连续 unresolved=3），未发送 START，不能视为 20000° 电机验收。已断 12 V、清理 pending A 并恢复原 B744，输出关闭、MCU 停在入口，未重试。

按后续请求新增单独 A 的 [TWO_SAMPLE 100/40 候选](docs/adc100-return40-candidate-20261020.md)：可疑跳变门槛 100、回旧值容差 40 ADC 计数，确认新值仍为 25、连续 unresolved 仍为 3；独立安全保护不变。该候选尚未刷板，不能据离线边界测试宣称实机故障已解决。

该 100/40 候选的[一次空载状态机实测](docs/adc100-return40-fsm-board-20261020.md)已完成：约 8 秒到原 rundown 时间上限，净行程约 24.27 圈，无 CURRENT_INVALID，unresolved 最大连续 1；FOC max=31.56 µs、deadline/CCR late=0。最高观察 226.6 rpm、尾段均值 203.42 rpm，240 rpm 稳速未通过；空载无 CONTACT，不算完整拧紧验收。已关闭 12 V、恢复原 B748 并停在入口。

随后[一次固定工件自然接触流程](docs/adc100-return40-contact-board-20261020.md)记录了 RUNDOWN_ARMED、CONTACT_CONFIRM、80/100/120/150 mA 阶段、150 mA HOLD 和 COMPLETE OK，约 7.1 秒自然结束；FOC max=31.61 µs、deadline/CCR late=0，无保护故障。结束后 CONTACT 清零造成主机初始误报，已基于有序事件离线核对，未重跑；不能据此验收实际扭矩精度。已断 12 V、恢复原 B752 并停在入口。

新增独立 A 的 [speed PI anti-windup 候选](docs/speed-pi-anti-windup-candidate-20261020.md)：在已有 SB2/SB3 和条件积分基础上，只接纳到 Iq 饱和边界并从已提交积分计算输出，保留退积分与原制动；PI 参数、100/40 判别、保护和 FSM 不变。尚未刷板，不宣称速度稳定；S-curve 待此项人工实测稳定后再加。

该 AW1 的[一次空载对照](docs/speed-anti-windup-fsm-board-20261020.md)已运行至原 8 秒 TIMEOUT：最高观察 231.2 rpm、尾段均值 207.13 rpm，仍未稳定跟踪 240 rpm，不能据单次小幅提高证明优化有效。FOC max=31.61 µs、deadline/CCR late=0，无保护故障。已断 12 V、恢复原 B756 并停在入口；暂不接入 S-curve。

随后按请求[关闭 SB3 的 AW0 单次对照](docs/aw-no-sb3-fsm-board-20261020.md)：保持 AW、PI、保护及配方不变，2～7.9 秒同窗口平均从 206.61 提高到 236.99 rpm，尾段 230.70 rpm，通过预设 ±10% 初筛但仍有局部掉速。FOC max=31.55 µs、deadline/CCR late=0，无保护故障；空载到原8秒超时。已断12 V、恢复原B760并停在入口，未自动重试或加入 S-curve。

再按请求[撤销新增AW1、SB3仍关闭的L00对照](docs/legacy-aw-no-sb3-fsm-board-20261020.md)：原有条件积分和积分限幅保留，非取消全部anti-windup；同窗口平均236.15 rpm，与AW0的236.99 rpm差异不足1 rpm，暂未显示明确优劣。FOC max=31.81 µs、deadline/CCR late=0，无保护故障；已断12 V、恢复原B764并停在入口。

按最新请求准备独立 A 的 [SC1 S-curve 候选](docs/speed-scurve-candidate-20261020.md)：恢复新增 anti-windup 开启、SB3 继续关闭，仅替换 SPEED 参考斜坡；加速度上限200 rpm/s、jerk上限1000 rpm/s²，0→240 rpm参考约1.4秒。PI/FSM/保护/PWM pipeline不改，STOP和故障不经过轨迹缓停；A Flash仅余116 B。[后续一次空载实测](docs/scurve-fsm-board-20261020.md)到原8秒超时：FOC max=31.53 µs、deadline/CCR late=0、尾段239.93 rpm，但同窗口平均233.12 rpm且仍掉速，未证明优于线性AW0。完整起步参考未捕获，不把离线1.4秒当成实测轨迹；已断12 V、恢复B768并停在入口。

随后加入 [普通 PW_LOG 诊断 token 化候选](docs/pw-log-tokenized-default-20261020.md)：保持控制和机器协议不变，复用官方 token codec 和原 `[PWT]` 日志链；新A从229260降至211500 B，节省17760 B、剩17876 B Flash，RAM不增加。A/B编译、53项定向回归及12项UART/日志CTest通过，无新增警告类型；字典仅留ELF、不刷入BIN。原镜像和板上B保持不变，尚未刷板或部署鲁班猫，解码需同版本ELF。

新增独立 A 的 [AF1 加速度前馈候选](docs/speed-accel-feedforward-candidate-20261020.md)：沿用 tokenized SC1，`iq_ff=Ka×accel_ref`，与 PI 合并后统一限幅并做 anti-windup；Ka=0.0001875 A/(rpm/s)，峰值37.5 mA（原0.50 A的7.5%）。支持空闲 FF ON/OFF、压缩日志及在线对照指标；PI增益、FOC、S-curve、PWM pipeline和保护不改，正式B不变。仅完成软件构建/离线测试，未刷板或启动。

后续[AF1 FF ON一次空载板测](docs/accel-ff-fsm-board-20261020.md)已完成：运行8秒至原RUNDOWN_TIMEOUT，无电机保护故障；FOC max31.62us、deadline/CCR late=0、margin15.19us，FF峰值37.5mA、token解码生效。但仍局部掉速、settling未建立，尚无同条件FF OFF对照，不宣称改进或拧紧验收通过。已断12V、恢复原B772并停在入口。

新增A-only [FR1库仑摩擦补偿候选](docs/speed-friction-compensation-candidate-20261020.md)：按用户后续修订取I_FRIC=0.20A（原0.50A上限的40%，不是小幅标定值）、参考速度deadband=2rpm；PI+原加速度FF+摩擦项统一限幅/AW。支持空闲FRIC ON/OFF、三条压缩日志及正负方向分开指标。保留原PI/FOC/S-curve/PWM/保护/IRQ和正式B，本轮不刷板、不启动。

后续[FR1一次正向空载OFF/ON对照](docs/friction-off-on-board-20261020.md)：仅RAM切开关，ON起转约274→72ms、匀速MAE5.52→2.22rpm，但低速MAE13.08→16.89rpm、Iq指令峰值0.304→0.417A、过冲6.36→7.71rpm。两轮各8秒至原RUNDOWN_TIMEOUT，无保护故障、deadline/CCR late=0；负向未测，不宣称全面改善。已断12V并恢复原B启动选择（generation780），停在入口。

新增默认关闭的[固定±0.10A扭矩链诊断准备](docs/torque-chain-100ma-diagnostic-20261018.md)：单次约200ms，绕过速度/位置环，记录净位移与往返路程，不自动启动或修改电角零点；历史50mA证据另行保留。

另有显式选择的[正向0.20A直接限幅修正版](docs/torque-chain-200ma-direct-limit-20261019.md)，保留全部保护和200ms限时，不自动加流或运行；[上一轮被0.15A截断的记录](docs/torque-chain-200ma-diagnostic-20261019.md)单独保留。

新增默认关闭的[双向逐档breakaway-current诊断](docs/breakaway-current-diagnostic-20261019.md)，以及[每档5秒的自动顺序批测](docs/breakaway-five-second-batch-20261019.md)：逐档停机、检查静止后继续，异常中止整批；0.25A受现有0.20A限幅阻止，不自动写入摩擦补偿。软件准备不等于已完成实机实验。

最新另有默认关闭的 [20 rpm 动态速度环、±0.50 A 候选实测](docs/speed500-dynamic-board-20261019.md)：Iq 由原速度 PI 计算，不执行固定电流拧紧阶段；单次 5 秒测试已完成，但仍断续运动，速度跟踪未通过。

固定 +0.35 A／5 秒测试也未得到持续转动证据，当前暂停升流和调速度 PI，转为[输出关闭手拧角度链与人工单点 electrical-offset 诊断准备](docs/electrical-angle-chain-diagnostic-20261019.md)。新角度候选只完成离线/编译，未刷板；不自动扫点或修改正式电角零点。

## 目录

| 路径 | 内容 |
| --- | --- |
| `firmware_common/` | 共享驱动、FOC、保护、通信及升级模块 |
| `foc2_app_a/`、`foc2_app_b/` | A/B 应用及不同诊断、控制构建预设 |
| `foc2_bootloader/` | A/B 启动、试运行与回退 |
| `foc2/` | 早期工程，保留作参考 |
| `esp32_s3_gateway/` | ESP32-S3 网关 |
| `router_network/` | Router、RPC/Transfer 主机端与网络测试 |
| `lubancat_hmi/`、`upper_computer/` | 鲁班猫及 PC 上位机 |
| `network_server/` | 网络服务端 |
| `simulation/`、`tests/` | 仿真和离线测试 |
| `tools/` | 构建、诊断、升级与验收脚本 |
| `third_party/pigweed/` | 固定版本的官方 Pigweed 子模块 |

## 获取与构建

```sh
git clone --recurse-submodules https://github.com/giaozk888/stm32-foc-tightening-system.git
cd stm32-foc-tightening-system
```

已有普通克隆可执行 `git submodule update --init --recursive`。依赖版本见 [Pigweed 固定版本](third_party/PIGWEED_REVISION.md)。

STM32 构建需要 CMake、Ninja 和加入 PATH 的 `arm-none-eabi` GCC 工具链。先查看预设，再选择与目标槽和测试目的相符的版本：

```sh
cd foc2_app_a
cmake --list-presets
cmake --preset RcDeferredShadow
cmake --build --preset RcDeferredShadow
```

上述示例仅编译功率关闭的影子诊断候选，**不是推荐刷写或已验收的闭环版本**。构建输出目录被 Git 忽略。ESP32 另需 ESP-IDF；本机脚本中的工具路径需要按安装位置调整。Docker、格式化说明见 [开发环境](DEVELOPMENT_ENVIRONMENT.md)，其中明确区分已验证和未验证的步骤。

## 当前验收状态

新增默认关闭的 `TighteningIntentCandidate`：流程 FSM → ControlIntent → 原控制后端，保留已有控制参数与保护链，预留 trajectory/前馈/DOB 接口但不启用算法。首轮空载板测**未通过**：断续运动、未误判 CONTACT/OK，约1.7秒后 ADC 健康保护停机；已恢复原 B729、停在入口且输出关闭。见[重构说明](docs/tightening-intent-fsm-candidate-20261019.md)与[板测记录](docs/intent-fsm-no-load-board-20261019.md)。随后仅离线修复了底层故障被显示成 TIMEOUT 的映射问题；原RAM占空比可复现采样窗口差2ticks，未放宽窗口保护或更改PWM策略，详见[原因映射修复与窗口定位](docs/intent-adc-health-fix-20261019.md)。新修复候选尚未刷板，不能宣称闭环问题已解决。

另新增默认关闭的 `TighteningCommonModeCandidate`：在原SVPWM之后对三相CCR同量平移，保持量化后相间差值，争取固定ADC触发点的采样窗口；保留原窗口复核和无解关断。已做一次空载状态机实验，约5.3秒报NO_ROTATION，无CONTACT/OK；FOC最大31.54µs、deadline/CCR late均0。共模adjusted=0，本轮没有触发真正平移，不能据此声称旧窗口故障或断续运动已解决。见[共模候选说明](docs/pwm-common-mode-candidate-20261019.md)与[本次板测](docs/common-mode-fsm-board-20261019.md)。A槽Flash仅余68B。

截至 2026-10-19，最新 `Speed500mADynamicDiagnostic` 已完成一次空载 5 秒 SPEED 动态 Iq 实测：FOC 最大 28.82 µs、50 µs 超时 0、真实 CCR late 0、最小更新余量 5.14 µs，无保护故障，但**仍断续运动，未稳定跟踪 20 rpm**。软件速度全窗口瞬时峰值约 44.57 rpm；200 ms 快照中的 IqRef 最高约 0.410 A，不能把 0.50 A 输出上限当成实际固定给定。原 PI 积分上限未改。见[本次实测记录](docs/speed500-dynamic-board-20261019.md)。原 B 回退、bootloader、私有配置均保留，测试后已恢复 B 启动选择并停住 MCU。

起转建立门控已上板验证：未成功运动不能 CONTACT，未同时经过运动建立和接触确认不能 OK；未起转且持续高驱动需求时报 NO_ROTATION。见[门控与启动诊断说明](docs/rundown-established-startup-diagnostic-20261018.md)及[状态机实测](docs/rundown-guard-full-fsm-board-20261018.md)。更早的 [SB3 实测](docs/sb3-full-fsm-board-20261018.md)曾出现空载返回 OK 的假接触问题，不能把历史状态机完成解释为真实拧紧成功。最新源码也不是已确认的生产固件，软件启动诊断不能替代实际桥输出或扭矩测量。

最新动态速度候选的相关回归 91 项通过，A/B 均编译通过；这不是全仓测试全绿声明。较早冻结源码曾有全量 1212 项中 1199 通过、9 失败、4 错误的记录，仍有历史基线、源码匹配和本地证据依赖等未通过项。部分回放测试依赖未公开的本地采集，公开克隆不含这些数据。构建保留基线已有的 unused/RWX 警告，具体范围见各次记录。

部分板级脚本依赖特定固件哈希、串口、调试器及本地备份；这些条件不会随公开克隆提供，也不应直接批量运行 `tools/` 下的脚本。刷写前必须核对槽位、镜像与接线。主机仿真、协议测试和硬件验收需分别执行。

## 公开范围与凭据

公开源码、构建配置、测试及技术记录；不公开 Flash/NVS 原始备份、私钥、Wi-Fi/API 配置、数据库、运行日志、波形、编译产物和个人面试笔记。历史文档可能引用未公开的本地证据文件，这些链接在克隆后不可用。

凭据需在本地单独配置，不能写入源码。提交前可执行 `python tools/audit_git_publish.py` 检查暂存内容；这是启发式检查，不能替代人工审查。

第三方代码沿用各目录的原许可证。本次发布未为全部自有代码指定新的统一开源许可证；公开可见不等同于授予任意再分发许可。
