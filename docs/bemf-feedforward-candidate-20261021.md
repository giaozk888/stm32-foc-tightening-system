# 反电动势前馈候选 A（未刷板）

用户要求不再使用无明确收益的dq交叉解耦，改做反电动势前馈。
新独立预设 `BemfFeedforwardCandidate` 继承原运行配置 `DqOriginalRuntime`，
但关闭编译 `FOC_DQ_DECOUPLING_CANDIDATE`，不删除历史DQ镜像/回执。
正式B源码、保存镜像和板上启动选择均未修改；本轮没有连接调试器、串口或启动电机。

## 方法与参数边界

当前Park为 `d=alpha*c+beta*s, q=-alpha*s+beta*c`，逆Park为
`alpha=vd*c-vq*s, beta=vd*s+vq*c`。只加入永磁反电动势项：

```
Vd_cmd_raw = Vd_PI
Vq_bemf = omega_e_measured_rad_s * PSI_WB
Vq_cmd_raw = Vq_PI + Vq_bemf
(Vd_cmd,Vq_cmd) = 原有统一矢量电压限幅(Vd_cmd_raw,Vq_cmd_raw)
```

对应[Microchip PMSM dq电压方程](https://microchiptech.github.io/mcaf-doc/6.0.2/algorithms/foc/introduction.html#pmsm-voltage-equations)。
不加入 `-we*Lq*Iq` / `+we*Ld*Id`、Rs前馈、observer、速度/电流参数调节。
反转使用同一个带符号的omega_e；静止严格为0，不从speed target推导。
omega_e复用 `encoder_omega_e_rad_s`：原有滤波机械rpm乘一次10极对数、2pi/60，
不新建速度滤波/预测，不改原角度链及保护。

饱和时 q积分器跟踪 `Vq_limited - Kp_q*err_q - Vq_bemf`，仍受原积分器限幅；
不会把前馈误积分回PI，也不允许绕过原1.60 V矢量限幅。d轴跟踪不变。
OFF跳过加法（包括+0），主机实测350次迭代与无BEMF的原PI输出/积分器逐位相同。
仅正常accepted PI路径计算本项；invalid/hold、CUR_CONFIRM与PWM pending/入口commit所有者不变。

### 尚缺真实磁链，不能把编译示例当电机参数

工程没有可信 `psi_m` 或 `Ke`。Rs/Ld/Lq不能确定永磁磁链，也未使用早先低质量辨识值
或日志残差自动拟合磁链。默认 `FOC_BEMF_PSI_WB=0.0`，明确表示未标定；
`FOC_BEMF_ENABLED_DEFAULT=OFF`，此时 `BEMF ON` 返回 `UNCALIBRATED_PSI`。
配置未标定却要求boot ON、非有限/负数/异常格式配置或同时启用DQ都会配置失败。
配置范围[0,1] Wb是单位/输入合法性检查，不是新增或提高运行保护阈值。

PSI必须是相峰值永磁磁链Wb，即 V/(electrical rad/s)。
如果提供的是正弦线间RMS `Ke_LL_rms`（V/krpm机械转速），应先明确测量定义，再转换：

```
PSI_WB = Ke_LL_rms / (sqrt(3/2) * pole_pairs * 2*pi/60 * 1000)
```

相峰值/相RMS/线间峰值、V/rpm、V/krpm、电角/机械角常数不能混用。
铭牌Kv常涉及直流母线电压/调制约定，不应未经定义直接取倒数写入PSI。
后续先取得厂家明确Ke，或输出关闭、外部带动电机测开路线间基波RMS与机械转速，
确认波形/单位/接线后人工配置；不自动选择磁链或更新B。

## 修改文件

- `firmware_common/foc_bemf_feedforward.h`：纯前馈公式、配置有效性、52 B最新帧。
- `firmware_common/foc_bemf_feedforward_binding.inc`：仅任务上下文的本地ON/OFF/STATUS/VOLTAGE。
- `foc2_app_a/Core/Src/main.c`：PI后、统一限幅前加q前馈；饱和跟踪扣除前馈；reset失效最新帧。
- `foc2_app_a/CMakeLists.txt`：A-only选项、互斥、flux参数合法性与浮点字面量规范化。
- `foc2_app_a/CMakePresets.json`：新候选configure/build preset，DQ关闭。
- `tests/test_foc_bemf_feedforward.py`：真实PI提取、命令及冻结所有者/构建配置回归。

没有修改B、PI增益、速度S-curve/anti-windup/acceleration FF/摩擦补偿、
电流判别器、CUR_CONFIRM、阈值、PWM/ADC频率、IRQ、状态机和A/B逻辑。
旧 `DqOriginalRuntime` 在功能编译关闭后的隔离重构建与历史BIN逐字节相同，
SHA256=`95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`。

## 查询与记录

仅现有本地受限控制台提供，不增加远程启动入口：

```
MOTOR TEST BEMF STATUS
MOTOR TEST BEMF VOLTAGE
MOTOR TEST BEMF OFF
MOTOR TEST BEMF ON
```

ON/OFF必须IDLE、无START/STOP排队、闭环未运行且SD/MOE/AOE/CCER均关闭。
只有有效正磁链才能ON。切换只改RAM开关/诊断valid，不使能输出、不启动、不写KVS。
VOLTAGE是同一accepted PI帧的二进制快照，含seq、ADC source us、frame on、
voltage saturation、measured electrical mrad/s、Id/Iq µA、Vd/Vq PI µV、
Vq_ff µV和最终限幅Vd/Vq µV；STATUS另报PSI_NWB、CONFIGURED、DQ_CROSS=0。
ISR只做固定浮点计算/二进制赋值，无printf/UART；任务短暂屏蔽中断复制52 B，
解除后才格式化整数回复。原Pigweed tokenized配置保留，命令回复仍为兼容文本。
这些Vdq是控制命令，不是实测端电压，也不是实际latch/PWM生效证据；
实际CCR late/margin仍由未修改的原probe测量。该快照不是高频历史窗口。

## 编译与测试

| 构建 | Flash B | 静态RAM B | 状态 |
|---|---:|---:|---|
| A `BemfFeedforwardCandidate`，PSI=0、默认OFF | 219132 | 129440 | PASS |
| A `BemfCompileFixture`，PSI=0.0001、默认OFF | 219204 | 129560 | PASS，仅编译验证，禁止当作电机标定镜像 |
| A `BemfNoFeatureBaseline`，历史DQ配置、无新功能 | 219300 | 129600 | PASS，与原镜像完全相同 |
| B `BemfBUnchanged`，已有tokenized配置隔离重编译 | 210540 | 128792 | PASS，不替换正式/板上B |

非零PSI夹具只验证不会被编译器按0优化掉的真实前馈完整代码路径，
0.0001 Wb不是建议参数、不是测量结果，不刷板。
各构建保持原12条unused及1条RWX警告，无新增警告类别或最终构建错误。
构建日志位于 `tmp/bemf-build-{a,baseline,b,fixture}.log`。
首次夹具命令遭PowerShell将未加引号的小数拆分为`0`与`.0001`，导致`0f`编译错误；
已引号传参并规范化整数配置为浮点字面量，最终重编译通过，不留下待解决错误。

新增8项回归及96项相关现有回归通过（合计104，非全仓库所有历史测试）。
覆盖正反速度/零速、单位与极对数不重复、缺磁链/NaN拒绝、OFF逐位等价、
PI+前馈统一限幅及反饱和、真实本地命令busy/输出拒绝、无输出副作用、
原pipeline/电流确认/判别/encoder/速度与tightening路径冻结、无效配置拒绝。
日志：`tmp/bemf-tests.log`、`tmp/bemf-regression.log`（81）、
`tmp/bemf-dq-regression.log`（10）、`tmp/bemf-pi-regression.log`（5）。

## 后续人工板测顺序（本轮未执行）

1. 先取得有定义、可信的磁链/Ke。人工配置真实PSI并编译，默认OFF；
   查询核对配置。PSI=0时停在此步，不用编译夹具代替标定。
2. 明确授权后按原流程仅刷A、完整回读、保留B，先功率关闭校准/时序验证；
   尚未测新候选实际FOC耗时，不能拿上一镜像33.26 us当本版结论。
3. 人工确认现场条件，保持原配方与全部保护，先BEMF OFF再ON，对照相同工况。
   只在IDLE、输出关闭时切换；核对静止FF≈0、反转FF反号、统一限压。
4. 比较同帧Vq_PI/FF/总Vq、Iq跟踪、速度误差、积分器、饱和和FOC/CCR余量；
   无收益不升级B，独立保护触发即停止，不自动重试/升压/升流。
5. 当前镜像SHA已改变，不能直接绕过旧板测脚本镜像校验运行；后续刷写/采集
   工具需明确适配新镜像和新BEMF字段，不复用DQ开关冒充BEMF开关。

反电动势前馈软件候选已就绪；磁链未标定，等待参数确认及人工板测。
