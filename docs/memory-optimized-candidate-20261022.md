# candidate A 空间优化（2026-10-22）

仅代码/构建/离线测试，没有连接调试器、刷写、复位、启动电机或修改启动选择。
当前已验证旧镜像和正式B保留；优化作为两个显式新A preset交付，不静默替换板测镜像。

## 实测链接占用

Flash槽229376 B，链接RAM region131008 B（原64 B mailbox保留）。
RAM占用包含.data、.bss和原1536 B链接heap/stack保留区；不是运行期可用堆/任务栈的测量。

|构建|Flash旧→新|新Flash余量|RAM旧→新|新RAM链接余量|
|---|---:|---:|---:|---:|
|正常A：BemfFittedFluxCandidate → BemfFittedMemoryCandidate|219204 → 211584 B|17792 B|129560 → 124024 B|6984 B|
|同步诊断A：KaSynchronizedDiagnostic → KaSynchronizedMemoryDiagnostic|219100 → 211480 B|17896 B|130888 → 125352 B|5656 B|

两者均节省5536 B RAM、7620 B Flash。
同步诊断A的链接余量从120 B增至5656 B；并不等于最坏栈或实时安全已由硬件重新验收。

## 优化内容与边界

### 1. 日志引用池64 → 48槽：省3328 B RAM

`PW_LOG_STORE_SLOTS=48`，原每槽208 B，原13312 B改为9984 B。
`firmware_common/pw_log_store.h`默认仍64槽；新增边界检查48..64。
新A通过pigweed_platform的PUBLIC编译定义让库与所有使用者采用相同容量。
B CMake和既有默认容量未改。

没有缩短单条192 B记录，没有修改32 B token编码上限、Base64/文本格式或CRLF。
历史16条、待发24条、UART TX池8192 B、UART/CAN/Router引用生命周期和引用释放协议均未改。
token化继续生效，START/STOP/STATUS等机器协议仍是原文本。

**代价：最多同时保留的不同日志记录减少16条。**
历史/待发/异步镜像可能共同钉住记录，48不是对所有最坏并发组合的无丢日志保证。
池满继续走现有拒收和`dropped_pool`统计，不覆盖被DMA/快照/镜像引用的记录，不阻塞ISR。
没有把日志量假设当作安全证明；上板需检查实际负载下丢弃量。
若真实负载不够，可在该候选设回64槽，保留测试框架隔离带来的2208 B节省。

### 2. 通用板端单元测试构建隔离：省2208 B RAM及7620 B Flash

`PW_TARGET_UNIT_TESTS`默认ON，旧构建行为不变。两个新preset显式OFF：

- 从应用源列表排除`Middleware/pigweed/pw_unit_tests.cc`，避免注册构造函数被.init_array保留。
- StartupTask仅跳过`PW_UnitTestsRun()`调用；链接GC回收通用测试框架及其测试代码/字符串。
- 保留`PW_SmokeTest()`、`PW_Allocator_RunSelfTest()`、`PW_ThreadSmokeStart()`。
- BootHealth、校准、所有电流/编码器/时序/启动保护与健康门不变。

Flash减少来自.text 6000 B、.rodata 1616 B、.init_array 4 B，不来自token字典缩小。
字典仍为ELF INFO、非ALLOC/LOAD，不算入MCU烧录Flash。

## 未修改

FOC/current PI/speed PI、Ka、S-curve、摩擦补偿、BEMF、dq解耦、状态机、PWM一周期pipeline、
CUR_CONFIRM、TWO_SAMPLE/CURRENT_INVALID、保护阈值、IRQ优先级均未改。
RTOS heap仍40960 B；任务栈、链接保留栈/heap、RAM执行热路径和A/B分区未缩减。
启动任务少执行了通用单元测试，启动负载会变化；不能由此免除新镜像启动与时序预检。

## 构建

在`D:/new project/foc2_app_a`执行：

```powershell
cmake --preset BemfFittedMemoryCandidate
cmake --build --preset BemfFittedMemoryCandidate -j 6
cmake --preset KaSynchronizedMemoryDiagnostic
cmake --build --preset KaSynchronizedMemoryDiagnostic -j 6
```

两个新A通过，原正常A/同步A/稳定B亦重新构建通过。
各A仍为13条既有unused/RWX警告，无新增warning/error；主文件语法检查警告集合与原版相同。

|镜像|BIN SHA256|
|---|---|
|新正常A|5b0576c89925a0aaa9d60613d4fd78d736e85243d4919a81b0a754d5135668e8|
|新同步A|0ac68673e9934ccc20ad956bc1b8a7afb065132b2f6887ded39ae655bb6818c4|
|旧正常A（重编不变）|6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f|
|旧同步A（重编不变）|5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136|
|稳定B TighteningCommonModeCandidate（重编不变）|7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366|

新正常A ELF SHA256：`0c56f7a4f4964013f42d5ec61b5b52e41dfce15474db25c2eab592731d08a945`。
新同步A ELF SHA256：`73985f27856ab5bcbab4710938893638a8af2650056e737cc0851bb399739761`。

## 验证

共152项相关测试通过，不声称跑过仓库所有历史测试：

- 新`tests/test_memory_candidate.py`：6项，覆盖占用、容量边界、旧镜像SHA、默认兼容、
  主文件控制/保护/协议函数展开相等、StartupTask仅移除通用测试调用、实时对象相同、警告集合。
- Ka系列：36项，`tmp/memory-ka-regression.log`。
- speed系列：81项，`tmp/memory-speed-regression.log`。
- token压缩：5项，`tmp/memory-token-regression.log`。
- UART/日志/引用/DMA/快照/并发，48槽和64槽各12项：
  `tmp/memory-host48-tests.log`、`tmp/memory-host64-tests.log`。
  每种容量均包含60000条、4生产者的共享记录并发测试、满池拒收、陈旧引用、
  Clear/overwrite期间引用保活、DMA abort失败钉住记录、长日志及官方Base64编码边界。

ADC IRQ、ADC timing、编码器DMA、fast trig、zero robust、tightening FSM等独立对象逐字节一致。
链接地址改变仍可能影响实机时序，不能以对象相同替代板测。

## 后续人工板测

1. 仍按原断开12 V/保留B回退流程，仅暂存新非活动A，完整回读与身份校验。
2. 先校准、输出关闭的时序预检；核验栈余量、FOC max、deadline、CCR late/margin。
3. 检查LOG STATUS、UART丢字节及日志完整性；pool_used/dropped_pool可用同版本ELF在停机后的RAM中核对，
   现有LOG STATUS文本没有新增这两个字段，不伪称能直接从其旧文本读取。
4. 预检通过且人工再次授权后，才运行原参数空载状态机；本轮没有执行。
5. 64点诊断ABI和数据字段保留，但地址已变化；必须用新ELF和同一轮Flash/RAM解码。
   既有脚本绑定旧BIN/ELF SHA，不直接套用、不修改旧回执或放宽身份检查。

## 修改文件

- `firmware_common/pw_log_store.h`
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`、`Core/Src/main.c`
- `tests/uart_zero_copy_host/CMakeLists.txt`
- `tests/test_memory_candidate.py`
- 本文

空间优化候选已就绪，等待人工板测。未刷板，正式B不变。
