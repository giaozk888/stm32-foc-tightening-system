# 普通 PW_LOG 诊断 token 化候选（2026-10-20）

按用户请求，把原先走 `pw_log_string` 的普通 `PW_LOG_*` 接入 token 化，不只是保留 LOGTOK 演示。仅软件修改、编译和离线验证；没有刷板、复位、启动电机、部署鲁班猫或修改 B 启动选择。

## 构建选择

- 新开关 `PW_LOG_TOKENIZED_DEFAULT`，默认 OFF，保证旧构建和已上板证据不被静默替换。
- 新 A preset：`Tightening240rpmScurveTokenizedCandidate`，继承 SC1，开关 ON。
- 新 B preset：`TighteningCommonModeTokenizedCandidate`，继承旧 CommonMode，仅用于编译核验；不修改板上稳定 B。
- CMake ON 时只选择 `firmware_common/pw_log_tokenized_override` 和官方 tokenizer indicator，不再把 `pw_log_string/public_overrides` 放入后端搜索路径。
- 旧 SC1 A 和 CommonMode B 的 BIN SHA256 不变，原板测脚本的精确镜像校验不能直接套到新候选。

## 日志路径

`PW_LOG_* → token + 编码参数 + metadata → 原 PW_Log_EnqueueTokenized → 原 RAM 引用池/历史 → [PWT] Base64 → 原 UART/CAN/Router → 鲁班猫或电脑`

编码器仍是仓库内 Pigweed 官方 `_pw_log_tokenized_EncodeTokenizedLog`，保留原 32 B 编码 buffer、level/module/line/flags 元数据、运行时级别过滤和现有队列丢弃计数。没有增加 ISR 日志、printf/UART、动态分配、重试或更改发送优先级。token 化会在日志调用处编码，不应把 PW_LOG 搬入实时 ISR；现有 ISR 拒绝入日志队列路径保留。

普通日志及使用该 facade 的 Pigweed 断言诊断改为 token 表示，但断言条件、捕获值、终止行为不改。`PW_Log_TestBurst` 等显式文本兼容路径保留。

START/STOP/STATUS/GET、FW/IAP、校准/时序应答等直接 UART/`snprintf` 机器协议仍是原文本；没有全局替换 printf，也不把命令回复 token 化。控制算法、PI、S-curve/AW、FSM、阈值、TWO_SAMPLE、CUR_CONFIRM、PWM pipeline、IRQ 和 A/B 升级逻辑没有修改。

## C++ constexpr 兼容

直接全局使用官方 metadata override 时，Pigweed constexpr 方法内的断言会展开出局部 static 字典项，现有 C++17/20 不允许，因此初次候选构建失败，没有刷板。

项目薄封装继续使用官方 token/hash/metadata/varargs 编码，只将字典声明改用 `PW_TOKENIZE_STRING_EXPR` / `PW_TOKENIZE_STRING_MASK_EXPR`（官方表达式 API 在子 lambda 内保存字典）。C 仍直接使用官方 metadata 宏。参数类型检查和实参编码保持在原调用处；未切 C++23、未改第三方源码、未删除断言或保护。测试覆盖 `__func__` 仍为调用函数名、`++value` 只执行一次、constexpr 未执行分支、模板函数以及 C frontend。

## Flash / RAM 实测构建占用

以下为链接器 region Used Size，不是 ELF 文件大小。Flash 槽 229376 B，RAM region 131008 B。

| 构建 | Flash 旧→新 | 节省 | 剩余 Flash | RAM 旧→新 |
| --- | ---: | ---: | ---: | ---: |
| A SC1 | 229260→211500 B | 17760 B | **17876 B（17.46 KiB）** | 128832→128832 B |
| B CommonMode | 228300→210540 B | 17760 B | 18836 B（18.39 KiB） | 128792→128792 B |

因此新 A 不再只有 116 B 余量。节省来自诊断格式文本和相关调用代码/链接可达性变化，不是把运行日志记录搬出 RAM，也不是把所有 17760 B 都归为字符串。

`.pw_tokenizer.entries` 在 A ELF 内约 228623 B，但为 INFO、VMA=0、无 ALLOC/LOAD；**不进入烧录 BIN、不占 MCU RAM/Flash region**。ELF 变大不等于固件变大。实际测试确认 `Pigweed alive`、allocator 格式文本在字典而不在 BIN，STATUS/FW/FILTER/保护标识文本仍存在。

新 A BIN SHA256：`8ebb728b8b3a368fdd0b1a75daf2de72b792f0c0c407d376cbafc41920ef82f0`。

新 A ELF SHA256：`8f8be920a9d54b3194cde01d3fe884f7d51a9539f257426eadf5fae406705b99`。

新 B BIN SHA256：`174ebaa1dd2580222cf5a48bb331b03eb06c1247cb2cd44c0e40b7cef57bfe5b`。

新 B ELF SHA256：`f85016f2f08a7280423181284502b47ad456ceb9ca94a25a5ed2cd2648e4075f`。

## 解码与兼容边界

鲁班猫原日志页能保留 `[PWT]`，当前可能显示 token/待字典解码，不是假装已完成屏内实时还原。使用已有离线工具，必须选择**产生日志的同一版本 ELF**：

```powershell
python tools/detokenize_hmi_logs.py capture.jsonl --elf foc2_app_a/build/Tightening240rpmScurveTokenizedCandidate/foc2.elf --output decoded-new.jsonl
```

工具保留 raw、增加字典 SHA256，未知 token 保持失败且不覆盖旧输出；查表成功本身不证明字典匹配，仍要核对实际固件身份。解码可在电脑或具备同一 Pigweed Python 环境的鲁班猫进行，本轮未部署。

token 化不是无损压缩任意文本：常量格式串变 token，整数等参数紧凑编码；运行时 `%s` 字符串仍要传输，原 32 B 编码上限可截断长字符串。保持现有限额，不扩大 buffer，不宣称任意长消息完整。

## 验证

- A/B 新候选编译通过；最终 warning 类型与各自旧候选相同（13 类既有 unused/RWX），无新增 warning/error。
- 53 项定向 Python/native regression 通过：`tmp/log-token-regression-20261020.log`。
- 12 项 UART/共享日志/Router/allocator-hybrid CTest 通过：`tmp/log-token-shared-ctest-20261020.log`。
- 原生 C / C++17 / C++20 使用真实官方编码器，核对空消息、正负整数、浮点、字符串、函数名、单次求值、模板/constexpr，以及原有长字符串截断边界。
- 真正 ARM ELF 字典与已有 HMI decoder round-trip 通过，确认格式/参数和 raw 保留。
- 预处理后 FOC、外环、保护、PWM pipeline、FSM、Protocol_HandleLine/PrintStatus 和日志队列/编码入队实现与旧配置逐函数相同；ADC timing 和 IRQ 对象逐字节一致。
- 原有 A/B BIN 校验值不变，本轮未触碰设备。新的任务峰值栈、上位机显示与板端时序仍需人工上板重新验收，不能以离线验证代替。

## 修改文件

- `firmware_common/pw_log_tokenized_override/pw_log_backend/log_backend.h`
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`
- `foc2_app_b/CMakeLists.txt`、`CMakePresets.json`
- `tests/pw_log_tokenized_default_host.c/.cc`、`tests/test_pw_log_tokenized_default.py`
- README、本文及鲁班猫日志说明。

普通诊断日志 token 化候选已就绪，尚未刷板。
