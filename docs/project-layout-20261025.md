# 项目目录整理与维护入口（2026-10-25）

本轮目标是整理当前候选 App A 的源码职责，不改变算法或运行参数，不修改正式 B，不操作硬件。现有未提交的算法、仿真和测试工作全部保留，没有进行批量删除、移动实验结果或改写 Git 历史。

## 从哪里开始看

| 要看 / 修改的内容 | 入口 |
| --- | --- |
| A 启动流程、初始化调用顺序 | `foc2_app_a/Core/Src/main.c` |
| A 模块职责、包含顺序及新增功能放置规则 | `foc2_app_a/Core/Src/App/README.md` |
| A 板级初始化 | `foc2_app_a/Core/Src/App/board/app_board.c`、`.h` |
| A 拧紧流程与模式绑定 | `foc2_app_a/Core/Src/App/application/` |
| A 电机任务、电流环、外环及功率控制绑定 | `foc2_app_a/Core/Src/App/control/` |
| A 编码器、PWM/ADC 采样和中断绑定 | `foc2_app_a/Core/Src/App/sensing/` |
| A 通信、命令与会话 | `foc2_app_a/Core/Src/App/protocol/` |
| A 配方、持久化和 IAP 接口 | `foc2_app_a/Core/Src/App/storage/` |
| A 健康监控与诊断输出 | `foc2_app_a/Core/Src/App/diagnostics/` |
| 可复用算法 | `firmware_common/` 中对应 `.c/.h`，例如 `speed_scurve`、`speed_accel_feedforward`、`mechanical_dob_monitor`、`tightening_intent_fsm` |
| 正式 B / 回退应用 | `foc2_app_b/`，本轮不迁移 |
| 启动与 A/B 镜像选择 | `foc2_bootloader/` |
| Simulink 模型生成、回放与指标 | `simulation/dob_simulink/` |
| 主机离线回归、C 测试适配 | `tests/` |
| 构建、取证、解码和分析工具 | `tools/`；板测脚本仍需原授权及匹配的镜像 |
| 实验说明与人工验收记录 | `docs/` |
| ESP32、鲁班猫、网络与上位机 | `esp32_s3_gateway/`、`lubancat_hmi/`、`router_network/`、`upper_computer/`、`network_server/` |
| 本机临时产物与冻结证据 | `tmp/`、各 `build/`、`refactor_backups/`；不是算法源码入口 |

## 本次拆分范围

`main.c` 从 13406 行整理为 188 行。时钟与六个 MX 外设初始化迁入独立编译的 `app_board.c`（含文件头共 446 行）；其函数体、初始化顺序、管脚及 ADC 配置保持原样，仅六个 MX 函数由私有静态链接改为板级接口。

其余内容按职责拆成 22 个私有 `.inc` 绑定文件，保留原声明顺序、静态状态和编译所有权。它们仍由一个编译单元编译，不能称为 22 个独立 C 模块。这样先解决源码集中在 `main.c` 的维护问题，避免同时引入实时调用边界、广泛 `extern` 和状态同步变化。应用状态继续集中于 `state/app_state.inc`，后续要逐个用明确接口封装；本轮没有宣称完成所有全局状态解耦。

FOC、电流/速度 PI、S 曲线、前馈、摩擦补偿、DOB、FSM 判据、保护阈值、IRQ 优先级及 PWM 一周期流水线均未修改。共享算法源码未因本次整理而改动。正式 B 的源码和构建策略与整理前哈希一致。

## 兼容与证据

历史源码契约原来直接读取整个 `main.c`。本轮将相关测试和少数源码提取工具改为通过 `tools/app_a_source_layout.py` 读取当前实际拆分内容；没有修改它们的断言或放宽保护。实际预处理、语法编译和链接仍直接使用真实源码。

新的 Simulink 准备脚本会把 `App/` 下真正参与编译的 `.inc/.c/.h` 以及布局描述加入输入哈希清单，避免以后只固定 `main.c` 却漏掉模块实现。历史结果清单、旧 DLL、旧板测镜像及执行器的镜像哈希不更新；旧源码固定结果不再与当前源码哈希相同时，需使用其冻结来源复核，不能覆盖旧证据。

整理前快照保存在本机 `refactor_backups/20261025_app_layout/`。该目录受现有 `.gitignore` 排除；新布局测试只依赖布局中记录的原始摘要，不要求克隆仓库后存在本机备份。深入的整理前/后审计工具则明确依赖本机冻结的预处理输出和目标文件。

## 验证记录

最终编译、回归和资源占用见同目录的 `project-layout-validation-20261025.md`。本轮没有烧录，没有启动电机。目标文件一致性不能替代板上 WCET、栈或负载性能验收。

## 后续维护顺序

新增算法实现放到对应 `.c/.h`，以显式输入、输出和状态结构提供接口；任务/中断中的接线留在所属绑定。新增功能不再堆入 `main.c`。

下一步若继续将旧绑定迁成独立 C 模块，应先从通信、配方和结果服务的私有状态开始，一个模块一次；实时 FOC、ADC IRQ 和外环的编译边界另行核验。不要同时整理文件、调 PI 和改变保护，以免无法归因。
