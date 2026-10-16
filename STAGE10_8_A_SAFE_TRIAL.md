# Stage 10.8｜A 槽 ESP 安全通信试运行

> 2026-09-26 当前状态：A 槽安全通信试运行已成功，**未确认 A 为正式槽**；启动元数据为 confirmed=B、pending=A、attempts_left=1。用户明确选择**保留 A 待试运行、不复位**。不要在未按 B1 的情况下随意复位或重新上电。

## 升级前

- 用户实测 PD6010B 输入端 12 V、CTRL_SD 0 V。STM32 原先停在 SRAM 诊断程序。
- 用 ST-LINK 只读备份 A/B 整槽和 V3 双份元数据到 `stm32_esp_stack_diag/pre_trial_*_20260926.bin`；与 Stage 10.4 备份逐字节相同。较新元数据 generation 234：confirmed=B、pending=none。已确认 B 的 226488 B CRC32=`14E28827`。
- 新 A 镜像 `foc2_app_a/build/Debug/foc2.bin` 为 213088 B，CRC32=`50101757`，SHA256=`D44E8A57DD65CFBF6E0A4DE98E30FBF55F35E58EDD5071322713CDBFCA668489`。

## 过程与结果

1. 复位到已确认的 B。COM5 看到静态/运行电流零点校准通过、编码器 20/20 正常、20 kHz ADC/FOC 运行、IDLE、`FLT=0`。B 启动时日志明确显示 `CTRL_SD=HIGH`，故不可把复位前的 0 V 读数当作 B 运行状态；没有发送 `START`。`FW STATUS` 显示 `CURRENT=B TARGET=A ACTIVE=0 CONFIRMED=B PENDING=- GEN=234`。
2. 运行 `foc2_app_a/iap_update.py` 对 COM5 发 `FW BEGIN` 和 6659 个 `FW DATA` 分块。固件在 `FW BEGIN` 时进入安全状态、关闭桥；所有 213088 B 均收到 ACK，无重试/写入错误。升级脚本新增 `--pause-before-end`，但本次非交互终端的 `input()` 收到 EOF，导致脚本退出，**没有发送 `FW END`**。这是主机交互问题，不是设备数据传输失败。脚本已补上 EOF 的明确提示。
3. 独立查询 `FW STATUS`：`ACTIVE=1 RX=213088 SIZE=213088 EXPECT=0x50101757 CONFIRMED=B PENDING=- GEN=234`。用户实测 CTRL_SD 0 V，并按住 B1。
4. 独立发送 `2200 FW END`，返回 `OK FW END TARGET=A SIZE=213088 CRC32=0x50101757 COMMIT=BOOTLOADER ATTEMPTS=2 RESETTING`。Bootloader 复核 CRC 并安排 A 试运行。
5. A 槽进入安全通信分支。COM5 周期输出 `SAFE COMM ESP_NODE=1`、`DISC_RX=2→6`、`PARSE_ERR=0`、`SD_ODR=0 MOE=0`。用户在 A 试运行期间实测 CTRL_SD 0 V。**用户没有观察电机，故不能记录为“电机无动作”。**
6. 不停止目标地只读检查两份元数据：较新 copy1 generation 236 为 confirmed=B、pending=A、attempts_left=1、A size=213088、CRC32=`50101757`；copy0 generation 235 记录试运行前的 2 次机会。GPIOC ODR=`0x00000000`；TIM1 BDTR 的 MOE 位为 0。没有发送 `FW CONFIRM`。

## 边界与后续

这次证明的是**完整 A 槽固件的安全启动分支**、ESP discovery、Router 与功率级关闭状态；不证明 A 正常 FOC 启动、拧紧流程、长时稳定性或升级最终确认。当前 A 仍是待试运行槽，下一次复位会消耗最后一次机会；若 B1 没按住，A 会走正常启动路径。建议先把驱动电源降至 0 V，再受控回退到已确认 B，或在另一个受控步骤里进行 A 的完整电机验收。

用户选择暂不回退也不复位，因此不能代替用户执行回退、确认或新的电机测试。若要降低待机风险，可以在**保持 NUCLEO USB 和 ESP USB 连续供电、不按 RST**的前提下关闭单独的 12 V 驱动/继电器电源；这不改变启动元数据。若无法确定关 12 V 是否会让 MCU 复位，则先不要切换供电。下一次继续前重新读取元数据并核实现场电压。
