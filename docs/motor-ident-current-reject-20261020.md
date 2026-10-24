# 辨识单点电流越界：记录/剔除，持续异常退出

## 范围

用户要求取消额外诊断中“单点 abs(Id)/abs(Iq)>0.20 A 就退出”的行为，按已说明的
单点剔除、持续异常退出实现。新增独立 preset
`MotorParameterIdentificationRejectDiagnostic`，继承原辨识诊断，开启
`FOC_IDENT_CURRENT_REJECT_ENABLE`；默认 OFF。
旧诊断镜像、正常 candidate A、正式 B 和历史 ELF/板测收据继续保留。
没有连接设备、刷写、复位或注入电流；板端仍是此前安全恢复的 B808、输出关闭。

## 新行为

- 正常有限值且未超 0.20 A：`current_good_count++`，连续 reject 清零。
- 单对超过 0.20 A：`current_reject_count++`、连续计数增加，标记 sample_rejected，
  不进入 32 帧辨识 estimator 窗口，但不立即退出。
- 连续 **3 对**越界：退出 MID_CURRENT；没有把门限改成更大的 A 值。
- 单次累计允许最多 **16 对**，第 **17 对**退出；不允许无限零散地吞异常。
- 电压向量 >0.20 V、转子机械位移 >0.10°、速度 >2 rpm、非有限值、时间/seq
  不连续、原保护/STOP 等仍按原顺序退出，没有被 reject 分支跳过。
- Rs 最多 400 ms、Ld/Lq 最多 104 ms，原 task wall-time cap/独立 lease 保持。
  缺少足够有效数据会报告 insufficient，不为了补点延长注入时间。

**sample admission 只影响参数估计，不替代 PI 的测量选择**。原 TWO_SAMPLE /
CUR_CONFIRM 和电流 PI 对已接受反馈的处理仍保持原样。本次不新增替代电流、
不改滤波/PI、不改 current invalid 或硬过流门限。若该测量使原 PI 产生超过
0.20 V 的诊断电压，仍会立即原安全 STOP，不绕过这条检查。

Ld/Lq 的连续瞬态若包含剔除造成的 gap，host 仍拒绝拟合，不能用相邻值补洞
冒称完整 RL 响应。Rs 仅使用 accepted 窗口，Python 继续检查跟踪/噪声/漂移质量。

## 第一对越界证据

第一次越界当场保存，后续不覆盖，且在 STOP 清参考值之前完成：

- timestamp、seq、pending source、IdRef/IqRef、Id/Iq。
- 对应 `cl_frame.u/v` 原码、角度、速度、mode/status/reason。
- **PREVIOUS calculated Vd/Vq**：明确是进入本帧 PI 之前已有的命令，
  不是本帧新电压，也不是物理相电压实测。
- binary `first_reject_valid` 最后发布，ISR 内无 printf/UART。

停机冻结后读取新增只读命令：

```
MOTOR TEST IDENT REJECT
MOTOR TEST IDENT REJECT ROW
```

第一条含 REJECT/GOOD/RUN/MAX_RUN/REJECT_MAX=16/RUN_LIMIT=3/FIRST。
第二条含 FIRST_US/SEQ/RAW_U/RAW_V/D_UA/Q_UA/DR_UA/QR_UA/PREV_VD_UV/PREV_VQ_UV。
完整浮点 first_reject 结构在 RAM；UART 为整数缩放。正常 estimator ROW 保持48字节，
没有缩减32帧窗口。新增64B metadata，整个 `motor_ident` ABI=1660B（旧1596B不变）。
host decoder 识别新 reject 元数据并保留第一帧，guard 不把 reject 预算超限的结果
当作合格参数。估计输出不覆盖正式 PI/NVM。

## 修改文件

- `firmware_common/motor_identification.h`
- `firmware_common/motor_identification_binding.inc`
- `foc2_app_a/CMakeLists.txt`、`foc2_app_a/CMakePresets.json`
- `tools/motor_identification_report.py`
- `tests/test_motor_ident_current_reject.py`

## 构建/离线验证

新 diagnostic：Flash **213580/229376B**，RAM **130656/131008B**，链接通过。
RAM 余量仅352B，仍需以后实物 stack/timing 验收，不能声称已实测通过50us。
unused/RWX warning仍存在，未屏蔽；没有链接错误。
本轮一度 D 盘耗尽导致编译器 No space left on device；只将本轮新建、可重建的
构建文件经 SHA 校验迁入临时缓存，完成后已复制校验回原工作区普通目录，
没有删除源码、旧镜像或原始实测证据。临时缓存仍可恢复，不依赖目录联接运行。

新 BIN SHA256：`04cc4387e53614432c0671f6e7106763e5040789cbd6d8c6b6259606d6c41a6d`。
新 ELF SHA256：`4bc20b2393e1c23912930aaa4ca6b6a115e04771846ad9058c72b08eb401e09e`。

旧辨识 A、正常0.105A A 和 B 均再次构建/核验，其 BIN 分别保持：

- `15511c9bd4c3bb579773928bb70a2ffc5e08250b6ddf899bbfda6c10a3d81e4d`
- `3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`
- `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`

本轮 **22 项相关离线测试通过**：新 reject4项、原辨识6项、原RS50 runner4项、
原保护层8项。不是整个仓库全部测试。新增测试实际编译C核心与实际binding，
覆盖单点恢复/剔除、连续3对/累计17对停止、记录不覆盖、原码与参考前态、
不能越过电压/运动/时长检查、L窗口缺样拒绝及控制/保护/PWM函数冻结比较。

## 以后上板

旧 `tools/motor_identification_board.py` 仍严格固定旧镜像/1596B ABI，不能直接
拿来刷本版；它拒绝新镜像属于正确的身份保护，不可只换 SHA 绕过检查。
若人工请求复测，需要新独立 pinned runner、匹配1660B解码及 B808 baseline，
停机后增加读取 REJECT 两条命令。仍先只测 Rs50 单点，夹具/防护和物理供电
转换按原流程进行；不自动继续75/100mA或Ld/Lq。
