# 5 秒诊断 A：断电恢复刷写与回读通过

用户确认驱动板 12 V 已关闭后，沿用本次已授权的 inactive-A 恢复刷写范围操作。**没有激活 A、提交试运行、发送 START/Iq 或运行自动升档。**

## 核验与恢复

1. 固定本地 A BIN/ELF 身份：228972 B，BIN SHA256 `6f45621b2c76b1b7e66a36cb0041cd2fa58ab985d2cb7614ccf8e25756f8fd95`，ELF SHA256 `7ed371dc326690658fcb462d5e458953884f85f8a6cbaea6c413b7da6f91f157`。
2. 以先前失败完整 Flash SHA256 `a0605d0204685d99296bc8319985b32c7d4e9c3b9c89ad59da5e2f718d3303a9` 为实时比较输入，不冒用更早、A 内容不同的 B693 备份。
3. 当前完整 Flash、停机和输出关闭检查通过后，执行一次 `reset halt`。VTOR=0，未运行应用。复位后完整回读 SHA 仍是失败 SHA，表明简单复位没有消除那 56 B 差异。
4. 保持功率关闭，仅对非活动 A 执行一次 erase/write，`verify_image` 通过；完整 512 KiB 回读再次比较通过。
5. 第二个独立只读会话再读完整 Flash，与成功暂存快照逐字节一致；A 槽镜像摘要与目标 BIN 完全相同。

## 最终状态

- 已暂存：`BreakawayFiveSecondDiagnostic`，每档板端租约 5000000 us，原 ±0.20 A direct-Iq 限幅不变。
- 整个 B 槽、bootloader、启动 metadata、私有参数均与原 B693 备份逐字节一致；B 镜像 CRC 复算通过。
- confirmed=B，generation=693，pending=0、attempts=0；没有切换启动选择或强制确认。
- MCU 停住，VTOR=0，DHCSR=`0x30003`；SD=0、BDTR=0、CCER=0。
- **新 A 仅写入并验证，尚未进入运行，不能将此结果称为零点、FOC timing 或 breakaway 电机实测通过。**
- 12 V 仍按用户最后报告为关闭，后续未提示或要求开启。

成功完整 Flash SHA256：`d164de2f272ce5a04723dbeb841d59d5fc488f42b2ac3dcb96178119ba640ed5`。

## 收据

- 受控恢复暂存：`tmp/breakaway5-recover-stage-1792387737672260400.json`
- 成功完整 Flash：`tmp/breakaway5-recover-stage-1792387737672260400-staged.bin`
- 独立只读复核：`tmp/breakaway5-recovered-verify-1792387802191167200.json`

完整 Flash 文件可能含私有配置，继续仅保存在本地，未上传。

工具新增 `--recover-stage-off --drive-off-fixed`，要求真实驱动断电，绑定固定失败快照和固定新 A。它不会忽略 live-Flash 比较，不循环重试、不改 B/metadata，不 reset-run 或激活。若复位后镜像已完整正确，则跳过再次擦写，仅做校验/回读；本次实际并非该情况，确实重写了 A。

相关回归 33 项通过，日志 `tmp/breakaway5-recovery-tests.log`，含恢复仅写 A、输出关闭、精确失败输入、复位后无需重写分支、缺失断电状态/前置核对失败禁止编程。此次未修改固件，不复用旧电机数据证明新测试有效。

旧 no-reset 写入路径仍隔离为 `HALTED_STAGE_VALIDATED=False`。本次 reset/halt 后重写成功说明故障与该不复位会话/写入环境相关，但还不足以锁定具体根因；不声称已经证明线材、Flash 或 DMA 是原因。
