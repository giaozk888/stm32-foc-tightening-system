# 速度 PI anti-windup 小步候选（2026-10-20）

本轮只准备速度 PI 反积分饱和候选，不加入 S-curve、摩擦补偿、前馈或 DOB；不刷板、复位、改变启动选择或运行电机。板端维持上轮恢复的原 B752。

## 审计结果：原来已有部分 anti-windup

`FOC_EncoderSpeedUpdate` 原来已有：

1. ±0.35 A 积分夹紧。
2. 由 `P + I_candidate` 生成 Iq 并限幅；只在未饱和、退饱和或强制 bleed 时提交 I_candidate。
3. SB2 积分上升/卸载策略。
4. SB3 确认超速后限制最终电流指令，并把积分跟踪到限幅后的请求减去 P。

因此不能把既往速度波动或约 203 rpm 尾段直接归咎于“完全没有 anti-windup”。尤其在未饱和时，本轮算法与原来一致；没有证据保证这次改动能消除速度波动。

原条件积分还有一个命令/状态不一致处：饱和的这一拍使用了未接纳的 I_candidate 计算输出，但积分状态保留旧 I；跨越边界时也会拒绝整次积分，而不是只接纳到边界的部分。

## 新增行为

独立默认关闭 A 配置 `Tightening240rpmSpeedAntiWindupCandidate`，继承已实测的 `Tightening240rpmAdc100Return40Candidate`，只开启 `FOC_SPEED_PI_ANTI_WINDUP`。

新增无状态纯函数 `SpeedPiAntiWindup_Apply`：

- 未饱和：原候选积分全部接纳，PI 数学不变。
- 正向积分会使 `P + I_candidate > Iq_limit`：只允许积分到边界；如果旧积分已经在边界外，保持旧积分，不继续增大。
- 负向情况完全对称。
- 使积分往退饱和方向变化的更新仍允许，即使本拍输出仍饱和。
- 原强制 bleed/unload 不被新逻辑否决。
- 最终从“已提交积分”重新计算并限幅 Iq，然后仍执行原 SB3 制动/积分跟踪，最后只发布一次 `foc_iq_ref_A`。
- 只作用于 SPEED 模式的外环更新；POSITION 使用原分支，直接 IQ 阶段和 20 kHz 电流环不变。

例：P=0.20 A，旧 I=0.29 A，候选 I=0.31 A，Iq 上限 0.50 A。
原实现输出 0.50 A、积分仍 0.29 A；新实现积分接纳到 0.30 A、输出 0.50 A。
没有新 Kp/Ki、back-calculation 增益或扩大电流权限。

这不是电流环电压饱和跟踪，也不从测得 Iq 或 PWM 直接反算速度积分；若后续发现下游执行能力不足，需要另收同周期证据，而不是宣称本候选已解决所有层级饱和。

## 冻结与可识别性

- Kp=0.003 A/rpm、Ki=0.020 A/(rpm·s)、积分限幅 ±0.35 A、原速度参考斜坡均不变。
- 240 rpm、±0.50 A 速度电流限幅、300 rpm 保护边界、1.6 V 电压矢量限幅不变。
- TWO_SAMPLE 100/40/25/3、CUR_CONFIRM、零点准入、硬过流、编码器/时序保护、PWM pipeline 均不变。
- 相序、电角零点、方向、极对数、拧紧状态机/配方、CAN/Pigweed/IAP 不变。
- 没有新 heap、日志、循环或 20 kHz 插桩，也没有新可持久化控制状态。
- `MOTOR TEST PROFILE` 使用等长 `SPEED_CTRL=AW1` 标识；AW1 包含原 SB3，而不是取消 SB3。旧板测脚本会拒绝新镜像，后续上板须单独核对新 BIN/ELF 身份。
- S-curve 尚未实现/接入；保留现有轨迹接口，等本轮实机验证稳定后再做。

## 构建与测试方法

在 `foc2_app_a` 下：

```powershell
cmake --preset Tightening240rpmSpeedAntiWindupCandidate
cmake --build --preset Tightening240rpmSpeedAntiWindupCandidate
```

| 构建 | Flash | RAM |
| --- | ---: | ---: |
| 新 AW1 A | 228940 / 229376 B | 128808 / 131008 B |
| 原 100/40 A | 228620 / 229376 B | 128808 / 131008 B |
| 既有 B CommonMode 交叉构建（非板上 B 镜像） | 228300 / 229376 B | 128792 / 131008 B |

新 A 增加 320 B Flash，余量仅 436 B，RAM 不增加。原 A 和 B 构建的 BIN 哈希保持不变；不把本地 B 构建与实机原稳定 B 混为一谈。

新增回归包含正负饱和、部分边界接纳、持续饱和不积累、反向退积分、强制卸载、SB2 接触需求可达、SB3 两点制动及不重载旧积分。Os/O2 下运行真实 helper，也抽取预处理后的实际应用 PI 提交与 SB3 代码编译执行；不是手写简化控制器替代实装。

本轮 81 项定向回归通过：新 AW 6 项，加既有 SB1/SB2/SB3、100/40、CUR_CONFIRM、零点准入、pipeline、intent FSM 和接触/空载脚本测试（约 41.7 秒）。日志 `tmp/speed-anti-windup-regression-20261020.log`。这是定向集合，不宣称全部历史测试均通过。

预处理比较确认除 SPEED 分支的积分接纳外，完整外环恢复为原代码；其余冻结 FOC/保护/FSM 函数一致。`foc_adc_timing_stm32.c.obj`、IRQ 对象与旧候选逐字节一致。编译器宏比较：除新特性开关/头文件 guard，原参数宏全部一致。最终构建没有新增 warning；既存 unused/RWX 警告仍存在。

新 BIN SHA256：`d1c7a791540c51c4aa9967cb5202a488514f6d47a1ff43321a50c80a9c90bc6a`。

新 ELF SHA256：`7428601783a58e5882bde6adf59b9dbd86159c84a833c352843a69622ed599b0`。

## 后续人工验收范围（本轮未执行）

先做同配置空载单次比较，保留限时和所有保护，记录速度命令/参考、滤波与瞬时速度、P、I、最终 IqRef/Iq、积分限幅及 SB3 制动。检查持续饱和后的恢复、启动过冲、反向制动和电流限幅，不只比较最高转速。确认 FOC deadline=0、actual CCR late=0，并核对 margin。

此候选只可称离线准备完成，不能把旧镜像的 31.61 µs 等实测数当作新镜像耗时，也不能称已稳定。验证后再决定是否接入 S-curve，不能同时改两个算法而失去对照。
