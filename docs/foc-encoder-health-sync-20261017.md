# 编码器优先级健康检查同步

本轮仅修复上次板测发现的配置预期不一致，不操作设备、不刷写、不复位、不改变 B 槽启动选择、不启动电机。

## 代码修改

`firmware_common/protected_closed_loop.inc` 的 `ProtectedLoop_TimerHealthy()`：

- `AS5047P_DMA_FOC_FIRST` 分支：要求 ADC=2、TIM2/RX/TX=3。
- 原 `AS5047P_DMA_IRQ_PREEMPT_ADC` 分支：仍要求 ADC=2、TIM2/RX/TX=1。
- 其他旧分支保持原预期，TIM7 和计数器/时钟/使能检查保持不变。
- 没有跳过健康检查，也没有允许任意较低优先级；配置漂移仍使健康检查失败并沿现有路径锁定输出。

一拍 PWM pipeline、入口 CCR commit、实际 margin probe、TIM7 优先级、CUR_CONFIRM、current discriminator、FOC 数学、PI、SVPWM、频率及保护阈值不变。冻结校验会将这两处预处理分支改动精确还原，再比对修改前整个 binding 的 SHA256，避免把其他变化混入修复。

## 回归

新增 `tests/encoder_health_binding_host.c`，直接包含并执行实际 protected binding，而非复制判断函数。验证：初始化后正确优先级能通过；TIM2/RX/TX 每路遍历0..15、ADC遍历0..15时只接受预定值；错误TIM7、计数器配置或禁用守护IRQ均拒绝；运行中优先级漂移仍锁定输出并置 `CL_BAD_TIMER`。

旧保护/管线/编码器测试保留。所有历史板测镜像、ELF、收据和 runner 的哈希绑定保留，不覆盖旧 `EncoderReview` 镜像。

## 新构建位置

使用 `tools/encoder_health_offline.py`：独立目录 `foc2_app_a/build/EncoderHealthReview/EncoderFocFirst` 和 B 对应目录。完整构建与测试收据在 `tests/foc_adaptive_build/encoder_health_evidence/receipt.json`，不涉及任何设备/启动操作。

本轮只提供离线候选。是否通过启动零点、持续 FOC <50 µs 与真实 CCR margin，仍需下一轮人工授权上板验证，不能把修复前的单帧13.676 µs当作 normal FOC 测量。

17个相关配置全部编译通过，132项离线测试全部通过；12个旧配置的重建BIN哈希均与上轮离线收据完全一致。新A heavy镜像仍为228964 bytes，RAM占用129064 bytes，未增加Flash/RAM占用。新共享代码相对旧配置的源码告警增量检查通过；已有unused/RWX等历史告警仍存在，不宣称工程零告警。

- A heavy BIN SHA256：`c7eb539311b572e451589ec93b8c8eb4bdddcc4938e3c82c2f0911c45f434408`。
- A heavy ELF SHA256：`03407e5b186b9de756557b5fdcf2b955b9ca71cb0c56ed66e1f7f09443c9caea`。
- 上次失败的镜像与已停止板子的Flash保持原样；不能拿旧runner绑定的旧哈希去刷这个新BIN，后续板测须另行绑定新镜像和当前B恢复收据。
