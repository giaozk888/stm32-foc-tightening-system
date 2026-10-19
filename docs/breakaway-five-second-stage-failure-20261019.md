# 5 秒诊断 A 刷写：未通过校验，未激活

**后续已在用户确认 12 V 关闭后恢复 A 写入，并通过完整回读及独立复核，仍未激活或运行电机。** 见[恢复记录](breakaway-five-second-stage-recovery-20261019.md)。下文保留首次失败证据。

本轮用户请求“刷版确认”，只授权刷写确认，不执行电机测试。此前用户报告 12 V 一直开启，本轮没有将该状态伪记为断电。

## 过程与实际结果

1. 只读核验：MCU 原本已停在 B693，SD/MOE/CCER 为 0；完整 512 KiB Flash 与原 B693 备份一致，MCU 电压约 3.29 V。
2. 为避免通电时复位 GPIO，尝试新增不复位的 inactive-A 写入流程。写入前两次确认 CPU 已 halt、VTOR=B、PC6 为 push-pull output、PC6 IDR 低、SD/MOE/AOE/CCER 关闭及 TIM1 CEN=0。
3. 仅对 `0x08008000` 起的 A 镜像执行 erase/write，再执行 `verify_image`。没有 reset、恢复应用、试运行 mailbox、START 或 Iq 命令。OpenOCD Flash loader 会运行 SRAM 算法，这不等于恢复应用执行。
4. `verify_image` 失败：**56 B 不匹配，即 14 个 32-bit word**。首地址 `0x0800b344`，后续每组相隔 `0x3ef8`，最后 `0x0803e5dc`。后续完整 Flash 回读也存在完全相同差异，不是仅仅忽略得掉的校验显示问题。
5. 已执行既有 emergency-off/halt；随后只读重新核验和全 Flash 对照。没有重刷或激活。

## 最终板端状态

- MCU halt，PC=`0x2000002e`（调试算法 SRAM 内），不是应用正在运行，也**不是**停在 B 的 Reset_Handler。
- VTOR=`0x08040000`，DHCSR=`0x30003`。
- SD=0、BDTR=0、CCER=0，PC6 输入回读低且保持输出模式，TIM1 CEN=0。
- confirmed=B，generation=693，pending=0、attempts=0，原 metadata 字节未改。
- bootloader、整个 B 槽、metadata、私有参数分别逐字节与原备份一致，B 的镜像 CRC 复算通过。
- **A 已被此次写入替换但未通过校验，必须视为不可用；不能提交试运行或拿它执行自动批次。** 未声称 A 已恢复到原镜像。

完整失败回读 SHA256：`a0605d0204685d99296bc8319985b32c7d4e9c3b9c89ad59da5e2f718d3303a9`。

本轮目标 A 仍为 BIN SHA256 `6f45621b2c76b1b7e66a36cb0041cd2fa58ab985d2cb7614ccf8e25756f8fd95`；本地 BIN/ELF 身份核验通过不代表板上写入成功。

## 证据

- 原始只读核验：`tmp/breakaway5-inspect-1792387267449957800.json`
- 写入失败及 emergency-off 收据：`tmp/breakaway5-stage_halted-1792387371009163900.json`
- 同次失败完整 Flash：`tmp/breakaway5-stage_halted-1792387371009163900-failed.bin`
- 后续只读安全/字节保留核验：`tmp/breakaway5-stage-failure-review-1792387556274099300.json`

这些完整 Flash 文件可能含私有配置，只保存在本地，不上传公开仓库。

## 隔离措施与下一步

新增 no-reset 路径已通过 `HALTED_STAGE_VALIDATED=False` 隔离。CLI 和函数入口都会在接设备/编程之前拒绝它。模拟测试通过不能当作真实写入可靠的证据，不得设置开关以绕过本次失败。

目前只证明错误字呈规则间隔，**尚未确定根因**，不能归咎于电机噪声、线材或 Flash 损坏。未自动重刷、不自动清错、不启动 B 应用。

后续需驱动板 12 V 实际关闭、MCU 保持供电后，再准备受控 reset/halt 的 inactive-A 恢复流程；必须以本次失败 Flash 作为实时精确核对输入，保留 B/bootloader/metadata/私有参数。旧 `--stage-off` 绑定原完整 B693 Flash，A 当前内容已变，不可直接跳过比较或伪造旧 baseline。

本轮相关离线回归 31 项通过，包括 no-reset 路径隔离的回归，日志 `tmp/breakaway5-stage-tests-final.log`。未修改诊断固件、PI、相序、保护阈值或 PWM pipeline；没有电机实测结果。
