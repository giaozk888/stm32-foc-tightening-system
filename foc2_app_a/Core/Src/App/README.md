# App A 源码导航

本次只整理候选 A。`../main.c` 保留入口、初始化调用、任务启动和异常入口；正式 B 和历史板测镜像不迁移。

| 目录 / 文件 | 职责 |
| --- | --- |
| `board/app_board.c`、`.h` | 独立编译的时钟、GPIO、TIM1、SPI1、UART、ADC 初始化 |
| `config/app_includes.inc` | 特性头文件及条件编译依赖 |
| `config/app_types.inc` | 应用私有数据类型 |
| `config/app_config.inc` | 原应用常量和默认参数，数值保持原样 |
| `state/app_state.inc` | 应用状态、外设句柄的唯一定义 |
| `internal/app_declarations.inc` | 私有声明及原中断故障桥接 |
| `startup/startup_task.inc` | 启动校准、预检和任务创建 |
| `application/tightening_task.inc` | 拧紧任务及所选 FSM / 辨识模式绑定 |
| `application/tightening_results.inc` | 周期结果和结果队列 |
| `control/motor_service.inc` | 电机任务、已有控制和诊断绑定 |
| `control/power_current_loop.inc` | 功率开关、PWM、电流环及原保护入口 |
| `control/outer_loop.inc` | 编码器速度更新、外环和观察数据提交 |
| `sensing/encoder_service.inc` | 编码器服务 |
| `sensing/pwm_adc_service.inc` | PWM/ADC 采样服务 |
| `sensing/adc_irq_binding.inc` | 受保护 ADC IRQ 绑定及 HAL 回调 |
| `protocol/uart_transport.inc` | UART 接收及传输 |
| `protocol/session_events.inc` | 会话状态与事件 |
| `protocol/command_dispatch.inc` | 命令分发，调用已有应用功能 |
| `protocol/router_protocol_tasks.inc` | Router、协议和通信任务 |
| `storage/recipe_storage.inc` | 配方及持久化 |
| `storage/boot_update.inc` | IAP、镜像和启动选择接口 |
| `diagnostics/health_monitor_tasks.inc` | 健康监控与诊断任务 |
| `diagnostics/value_format.inc` | 原诊断格式化辅助 |

## 编译边界

`board/app_board.c` 是独立 `.c` 模块。其余 22 个 `.inc` 是按职责拆开的**私有绑定文件**，由 `main.c` 按声明顺序各包含一次，仍属于同一编译单元；不是 22 个独立链接模块。不要将这些 `.inc` 加进 CMake 源文件列表或从其他 `.c` 重复包含。

这是保留实时控制上下文的第一步整理：保持原静态状态、宏作用域、内联机会、IRQ 所有权和调用顺序，不为拆文件而增加全局变量、任务间消息或函数指针。`firmware_common/` 中原有的 PI、S 曲线、DOB、保护、FSM 等算法模块继续复用。本次没有完成所有应用全局状态的封装，也没有把通信与控制绑定全部改成独立 C 模块。

## 后续功能放置规则

1. 可复用算法优先使用 `firmware_common/<feature>.c/.h`，以显式输入、输出、状态结构测试，避免依赖应用全局变量。
2. A 专用、无实时依赖的新服务使用明确的 `.c/.h` 接口并加入 A 的 CMake；不要往 `main.c` 放实现。
3. 现有算法的任务接线放在对应 `control/` 或 `application/` 绑定；命令接线放在 `protocol/`，只负责校验和调用。
4. IRQ/FOC/外环迁出同一编译单元前，要单独核验状态所有权、内联变化、栈、代码大小及实际时序。不能把这次代码段一致性检查等同于新镜像的板测。
5. 保留 `main.c` 中的包含顺序。`layout.json` 记录本轮原始片段和审计映射；后续有意修改行为时，应同步更新相关测试契约。

## 离线核验

```powershell
python -m unittest discover -s tests -p test_app_source_layout.py -v
python tools/test_app_layout.py
# 从仓库根目录运行；本机冻结的整理前快照和新构建均存在时：
python tools/audit_app_layout.py
```

历史源码契约通过 `tools/app_a_source_layout.py` 展开**当前实际文件**，不把备份源码当作实现。外设初始化仅在此逻辑视图中还原原 `static` 声明，以兼容旧文本契约；真实 `.c/.h` 编译边界由新布局测试和实际构建检查。旧板测执行器的镜像哈希保持原样，不能拿新镜像冒充已验收镜像。
