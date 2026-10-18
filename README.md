# STM32 FOC 拧紧系统与多设备通信

基于 STM32G474、FreeRTOS 和 C/C++ 的电机控制实验项目，包含 A/B IAP、Pigweed 通信、ESP32 网关、鲁班猫上位机及主机测试工具。

这是开发与实验仓库，不是已通过工业认证的产品。历史记录中的离线通过、功率关闭计算、桥开关测试和电机闭环测试是不同验收范围，不能相互替代；没有扭矩仪的模拟测试不能证明真实扭矩精度。

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

截至 2026-10-18，最新 `SpeedBrakeTrackTrial`（SB3）空载完整状态机运行返回 OK，但目标 20 rpm、板端滤波速度峰值仅 2.77 rpm，**速度控制未通过，提前制动效果尚未验收**。本轮 FOC 最大耗时 28.68 µs、50 µs 超时 0、真实 CCR late 0、最小更新余量 15.15 µs。完整结果和证据边界见 [SB3 实测报告](docs/sb3-full-fsm-board-20261018.md)。原接触条件可能把低速、高电流需求的不起转状态识别成接触；状态机完成不代表真实拧紧成功。仓库保留历史方案与实验记录，不能把“最新源码”直接当成已确认的生产固件。

最新全量离线运行共 1187 项，其中 1174 通过、9 失败、4 错误，仍有历史基线、源码匹配和本地证据依赖等未通过项，不能宣称全量测试通过。SB3 最终算法定向测试 10 项、完整状态机脚本测试 10 项通过；全量运行与最终定向测试不是同一原子源码快照，详见 [候选说明](docs/sb3-speed-brake-track-candidate-20261018.md)。部分回放测试依赖未公开的本地采集，公开克隆不含这些数据。

部分板级脚本依赖特定固件哈希、串口、调试器及本地备份；这些条件不会随公开克隆提供，也不应直接批量运行 `tools/` 下的脚本。刷写前必须核对槽位、镜像与接线。主机仿真、协议测试和硬件验收需分别执行。

## 公开范围与凭据

公开源码、构建配置、测试及技术记录；不公开 Flash/NVS 原始备份、私钥、Wi-Fi/API 配置、数据库、运行日志、波形、编译产物和个人面试笔记。历史文档可能引用未公开的本地证据文件，这些链接在克隆后不可用。

凭据需在本地单独配置，不能写入源码。提交前可执行 `python tools/audit_git_publish.py` 检查暂存内容；这是启发式检查，不能替代人工审查。

第三方代码沿用各目录的原许可证。本次发布未为全部自有代码指定新的统一开源许可证；公开可见不等同于授予任意再分发许可。
