# Stage 5.4 pw_kvs 参数存储

A/B APP 已接入 Pigweed KVS，使用 Bank2 Page112–119，地址
0x08078000–0x0807BFFF，共 16 KiB。每页 2 KiB，写入对齐 8 字节。
Metadata Page125/126、旧参数 Page127 与 APP 链接地址保持原值。

参数以 tighten.params.v1 为键整体保存，配置双副本、KVS CRC16，
并保留原参数记录 CRC32。启动优先读取 KVS；缺少键时加载旧参数，
尝试迁移到 KVS。旧参数页保留为历史回退副本，不随新 SAVE 更新。

命令：
```text
2000 KVS STATUS
2001 GET PARAMS
2002 SAVE PARAMS
2003 LOAD PARAMS
2004 FW STATUS
```

验证记录：
- A/B clean build 成功。A Flash 207360 B、RAM 52032 B；
  B Flash 207040 B、RAM 52016 B。仍有原 main.c 未使用变量/函数警告。
- A 成功迁移旧参数；70→71→70 保存后 TXN=3，原参数恢复。
- 复位读取保持 RUNDOWN_RPM=70、CRC32=0x9083B9D5。
- B 经 IAP 下载、5 秒健康检查、自动确认及再次启动，读取同一 KVS。
- 最终 CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=125。
- KVS READY=1 ENTRIES=1 TXN=3 REDUNDANCY=2 INUSE=288
  RECLAIM=576 ERASES=0。
- RingBuffer 4 项测试通过；空闲运行 ADC/FOC 约 20 kHz，FLT=0。

验证边界：尚未做写入中断电、损坏单副本注入、填满后的垃圾回收测试；
REDUNDANCY=2 表示配置及正常存储结果，不能替代故障恢复验证。
软件复位验证不能等同于断电测试。Flash 擦写期间的实时控制延迟也未测量。
Debug 镜像已占 APP 槽约 90%，接入后续模块前需评估空间。

供电排查：PD6010B 未供 12V 时 ADC U/V 为 0，程序停在零点校准，
串口命令无法处理。恢复供电并复位后 U/V=1558/1562，启动恢复。
