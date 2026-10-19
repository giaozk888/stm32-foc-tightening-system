# STM32 FOC 拧紧系统与多设备通信

基于 STM32G474、FreeRTOS 和 C/C++ 的电机控制实验项目，包含 A/B IAP、Pigweed 通信、ESP32 网关、鲁班猫上位机及主机测试工具。

这是开发与实验仓库，不是已通过工业认证的产品。历史记录中的离线通过、功率关闭计算、桥开关测试和电机闭环测试是不同验收范围，不能相互替代；没有扭矩仪的模拟测试不能证明真实扭矩精度。

新增默认关闭的[固定±0.10A扭矩链诊断准备](docs/torque-chain-100ma-diagnostic-20261018.md)：单次约200ms，绕过速度/位置环，记录净位移与往返路程，不自动启动或修改电角零点；历史50mA证据另行保留。

另有显式选择的[正向0.20A直接限幅修正版](docs/torque-chain-200ma-direct-limit-20261019.md)，保留全部保护和200ms限时，不自动加流或运行；[上一轮被0.15A截断的记录](docs/torque-chain-200ma-diagnostic-20261019.md)单独保留。

新增默认关闭的[双向逐档breakaway-current诊断](docs/breakaway-current-diagnostic-20261019.md)，以及[每档5秒的自动顺序批测](docs/breakaway-five-second-batch-20261019.md)：逐档停机、检查静止后继续，异常中止整批；0.25A受现有0.20A限幅阻止，不自动写入摩擦补偿。软件准备不等于已完成实机实验。

最新另有默认关闭的 [20 rpm 动态速度环、±0.50 A 候选实测](docs/speed500-dynamic-board-20261019.md)：Iq 由原速度 PI 计算，不执行固定电流拧紧阶段；单次 5 秒测试已完成，但仍断续运动，速度跟踪未通过。

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

截至 2026-10-19，最新 `Speed500mADynamicDiagnostic` 已完成一次空载 5 秒 SPEED 动态 Iq 实测：FOC 最大 28.82 µs、50 µs 超时 0、真实 CCR late 0、最小更新余量 5.14 µs，无保护故障，但**仍断续运动，未稳定跟踪 20 rpm**。软件速度全窗口瞬时峰值约 44.57 rpm；200 ms 快照中的 IqRef 最高约 0.410 A，不能把 0.50 A 输出上限当成实际固定给定。原 PI 积分上限未改。见[本次实测记录](docs/speed500-dynamic-board-20261019.md)。原 B 回退、bootloader、私有配置均保留，测试后已恢复 B 启动选择并停住 MCU。

起转建立门控已上板验证：未成功运动不能 CONTACT，未同时经过运动建立和接触确认不能 OK；未起转且持续高驱动需求时报 NO_ROTATION。见[门控与启动诊断说明](docs/rundown-established-startup-diagnostic-20261018.md)及[状态机实测](docs/rundown-guard-full-fsm-board-20261018.md)。更早的 [SB3 实测](docs/sb3-full-fsm-board-20261018.md)曾出现空载返回 OK 的假接触问题，不能把历史状态机完成解释为真实拧紧成功。最新源码也不是已确认的生产固件，软件启动诊断不能替代实际桥输出或扭矩测量。

最新动态速度候选的相关回归 91 项通过，A/B 均编译通过；这不是全仓测试全绿声明。较早冻结源码曾有全量 1212 项中 1199 通过、9 失败、4 错误的记录，仍有历史基线、源码匹配和本地证据依赖等未通过项。部分回放测试依赖未公开的本地采集，公开克隆不含这些数据。构建保留基线已有的 unused/RWX 警告，具体范围见各次记录。

部分板级脚本依赖特定固件哈希、串口、调试器及本地备份；这些条件不会随公开克隆提供，也不应直接批量运行 `tools/` 下的脚本。刷写前必须核对槽位、镜像与接线。主机仿真、协议测试和硬件验收需分别执行。

## 公开范围与凭据

公开源码、构建配置、测试及技术记录；不公开 Flash/NVS 原始备份、私钥、Wi-Fi/API 配置、数据库、运行日志、波形、编译产物和个人面试笔记。历史文档可能引用未公开的本地证据文件，这些链接在克隆后不可用。

凭据需在本地单独配置，不能写入源码。提交前可执行 `python tools/audit_git_publish.py` 检查暂存内容；这是启发式检查，不能替代人工审查。

第三方代码沿用各目录的原许可证。本次发布未为全部自有代码指定新的统一开源许可证；公开可见不等同于授予任意再分发许可。
