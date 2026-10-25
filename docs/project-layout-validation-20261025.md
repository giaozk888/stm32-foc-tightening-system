# App A 目录整理验证（2026-10-25）

验证范围为代码布局、主机回归及编译。没有烧录、切换板上镜像或启动电机；没有据此宣称新镜像的真实运行性能或 WCET 已验收。

## 布局与代码审计

- `main.c`：13406 → 188 行；22 个按职责归档的私有绑定，另有独立 `app_board.c/.h`。
- 展开当前实际绑定文件、将板级冷初始化的六个新增外部声明归一化后，与整理前 13406 行源码精确相同。实现不是从备份加载的。
- 三个原有构建配置 `DobLoadSpeedContactHoldCandidate`、`TighteningDob025Trip500`、`FastCurrentRejectComputeOnly` 的实际预处理通过；配置中存在的所选 FOC/ADC/速度更新/故障关断函数与整理前相同。新板级 C 文件在三组实际编译标志下语法检查通过。
- 实际目标文件共有 111 个同名函数代码段可比较，其中 110 个字节一致。唯一变化为 `main` 不再内联原 MX 初始化；`SystemClock_Config` 从主目标文件迁入板级目标文件。这不是对链接地址、全部重定位或实机时序相同的声明。
- 正式 B 的 `main.c`、CMake 和 A 的预设与本轮开始时的摘要一致。原板测 A 的 BIN/ELF 与冻结备份摘要一致。

详细摘要及物理源码清单见 [机器可读报告](project-layout-validation-20261025.json)。本机深入审计命令为 `python tools/audit_app_layout.py`，需要整理前本机冻结证据存在。

## 构建

新建构建目录，保留历史板测产物。A 使用原 `DobLoadSpeedContactHoldCandidate` 配置，B 使用原 `TighteningCommonModeTokenizedCandidate` 配置；B 构建是源码复核产物，不代表替换板上正式 B。

| 构建 | 结果 | Flash | RAM |
| --- | --- | ---: | ---: |
| `foc2_app_a/build/AppLayoutCandidate` | 通过 | 229000 B / 229376 B | 130968 B / 131008 B |
| `foc2_app_b/build/AppLayoutBVerify` | 通过 | 210540 B / 229376 B | 128792 B / 131008 B |

本次 A 相比冻结候选增加 288 B Flash，RAM 不增加。该较满的诊断配置余量为 Flash 376 B、RAM 40 B；没有通过放宽保护、删控制功能或改优化级别使构建通过。保留链接器原有 RWX 段警告，未将其当成已解决。

初次构建/较大回归批次遇到主机编译器内存分配和分页文件资源错误；改为受控并发后，以上两个目录均链接成功，所列定向测试独立复查通过。没有修改操作系统分页设置或终止用户程序。

## 定向回归

`python tools/test_app_layout.py` 对应 19 个模块、123 项测试：0 失败、0 错误、0 跳过。覆盖布局、FSM、当前 PI、独立保护、ADC 时钟、超时、anti-windup、S 曲线、加速度/摩擦前馈、dq 解耦、DOB 质量、源缺口及负载调度。

另独立执行：

| 测试模块 | 通过项数 |
| --- | ---: |
| `test_adc_control_pins_low` | 9 |
| `test_foc_pwm_pipeline` | 9 |
| `test_isolated_spike` | 5 |

以上共 **146 项定向回归通过**，没有宣称 431 个 Python 测试模块的全仓库套件全部通过。

扩大检查时另外发现三项历史测试问题。使用整理前冻结 A 源码和当前拆分 A 源码分别执行，均为同样的两项失败和一项错误：

| 历史测试 | 整理前 / 后结果 | 原因 |
| --- | --- | --- |
| `test_feedback_safety_binding...test_ab_interrupt_lifecycle_and_default_protection_contracts` | 均失败 | 文本契约只在编码器故障函数前 350 字符内寻找关断，现有时序原因记录已使其超出这个片段 |
| `test_foc_fast_math...test_separate_candidate_and_fault_policy` | 均失败 | 仍假设 A/B 电流环源码完全相同，与 A 既有辨识 PI / 诊断分支不一致 |
| `test_control_chain_reconnect...test_actual_ab_current_pi_uses_filtered_frame_and_original_limits` | 均编译错误 | 旧主机夹具未提供现有电流环的 profiling 与 d/q PI 别名宏 |

这些断言或夹具没有为了获得绿色结果而放宽。其余补查中，PWM 和尖峰测试在资源恢复后重跑通过；前述 reconnect 模块为 17 项通过、1 项上述历史错误。后续可单独维护旧测试适配器，不能据本轮结果宣称全仓库无历史问题。

## 修改位置

应用实现修改为 `foc2_app_a/Core/Src/main.c`、新增 `Core/Src/App/`、A CMake 增加板级源文件。没有改 B 或共享算法。

辅助修改包括：历史源码读取适配、新布局测试、审计/定向回归入口、三个源码提取工具，以及五个 Simulink 准备脚本补全拆分模块的源文件摘要。历史报告、旧执行器镜像哈希、旧 Simulink 结果清单和已保存镜像保持原样。README 与项目导航说明当前目录职责和编译边界。
