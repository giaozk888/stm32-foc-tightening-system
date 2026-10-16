# Stage 10.5｜A/B APP Flash 体积优化（离线）

> 状态：2026-09-26 A/B 离线构建通过；**未烧录、未复位、未做完整 APP 上板验收**。板上已确认的 B 镜像和启动元数据保持原样。STM32 当前仍由调试器 halt，PD6010B 驱动输入应保持 0 V。

## 原因与策略

Stage 10.3 将 ESP32 discovery-only 链路移植到非活动 A 槽后，224 KiB APP 槽只剩 28 B；B 槽新源码只剩 372 B。不能继续靠缩短几条日志勉强塞入，也不能直接覆盖板上已确认的 B 槽。

仅在两套 APP 的 `CMakeLists.txt` 中，对低优先级的 `router.c`、`esp_link.c`、`modbus_probe.c`、`pw_log_router_bridge.c`、`pw_unit_tests.cc` 指定 `-Os`。ESP 文件原本已用 `-Os`，其余四项是本次新增的体积优化。**`main.c`、20 kHz FOC ISR、TIM1/PWM/ADC、HAL 驱动及链接地址没有改动**。Debug 构建命令里的 `-O0` 在前、单文件 `-Os` 在后，GCC 以后者为准。

## 实测构建大小

| 阶段 | A 槽 BIN | A 剩余 | B 槽 BIN | B 剩余 |
| --- | ---: | ---: | ---: | ---: |
| 优化前 | 229348 B | 28 B | 229004 B | 372 B |
| Router 单文件 `-Os` | 226340 B | 3036 B | 225996 B | 3380 B |
| 再优化 Modbus / 日志桥 | 224900 B | 4476 B | 224556 B | 4820 B |
| 再优化启动单元测试 | **212168 B** | **17208 B** | **211824 B** | **17552 B** |

两槽各节省 **17180 B**。最终镜像：A CRC32=`A0BCAA23`、SHA256=`FF1FACB56004A781042F06CE569F7A96B973281FDF41D3B9CEFB46C148B01D58`；B CRC32=`7D819EF1`、SHA256=`A5F5A445316C17BCBA4F3DF4201EB53010A8DE3BACEE9CEC09B46E1EBAAD7DC5`。A/B 向量表的 SP 和复位入口均落在预期 SRAM/槽地址范围。RAM 报告为 A 65344 B、B 65328 B，比优化前各少 16 B。

## 验证与限制

- `cmake --build 'D:\new project\foc2_app_a\build\Debug' -j 4`、B 槽同命令：均通过。
- `arm-none-eabi-nm -C` 确认 5 个 Pigweed 目标单元测试的注册符号和测试主体仍在 A/B ELF 中，`PW_UnitTestsRun` 没被删掉。
- `ctest --test-dir 'D:\new project\tests\as5047p_host\out' --output-on-failure`：4/4 通过。
- `python 'D:\new project\tests\tim1_pwm_adc_timing.py'`：A/B TIM1/ADC 静态时序一致、离线筛查通过；这不是模拟功率级的实测。
- Stage 10.4 的 SRAM 双板实测此前已直接编入 A 槽的 Router/ESP 源码，并以 `-Os` 编译，验证 `ESP_NODE=1`、`DISC_RX` 增长、`PARSE_ERR=0`。本次新改的 Modbus、日志桥和单元测试编译优化**尚未在完整 APP 上板运行**，需要后续回归。

**不要**把这两个新 BIN 当作板上已验证镜像。当前启动元数据仍匹配板上旧 B 的 CRC32=`14E28827`；直接用 ST-LINK 覆盖当前 B 会破坏已确认版本和 CRC 对应关系。正式升级应走非活动 A 槽 IAP，并先解决完整 APP 启动时先启桥、后启 ESP 链路的安全验证条件。
