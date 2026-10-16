# 诊断快照浏览与 CSV 导出（2026-09-29）

## 范围

- 第六个触控页“记录”列出最近 50 条 SQLite 诊断快照，包括编号、未校验的 UTC 墙上时间、样本数、缺序号数、时长和质量提示。
- 可点选一条后导出 CSV 到 `/home/cat/lubancat_hmi_snapshot/exports/capture-<id>.csv`。导出字段为 `kind,capture_id,captured_at_utc,clock_verified,sample_count,missing_sequences,duration_ms,sample_index,elapsed_ms,sequence,angle_mdeg,speed_deci_rpm`。原始量纲保留；`clock_verified=0` 不被当成可靠作业时间。
- 浏览使用 SQLite 只读连接，不存在数据库时不创建；CSV 原子写入，已有文件不覆盖，记录头样本数与实际行数不一致则取消导出。没有 CAN 发送或控制入口。

## 已验证

- Windows Qt6 与板上 Qt5 的 4/4 测试通过，涵盖只读列表、CSV 字段、重复导出拒绝、数据不一致时取消导出。
- 板上以现有数据库做离屏渲染，7 条快照均展示、缺序号标识与数据一致；预览图 `snapshot-browser-board-preview.png`。
- 独立 `build_browser` 部署后，HMI 服务 active/running、`NRestarts=0`；CAN 服务和 STM32 没有重启或改动。
- 用户现场从实屏导出 `capture-6.csv`；板上文件存在（24,705 字节），295 条数据行、12 个字段与数据库第 6 条的 295 个样本逐行完全一致。该记录时长 29,918 ms、缺序号 6、`clock_verified=0`，因此只可作诊断分析。
- 切换前后 `can0` 累计 bus-off 已从此前的 2 增至 15，当前 `ERROR-WARNING`，不是本次 HMI 切换造成的计数变化。总线可靠性仍不合格。

## 尚未验收

- 整机重启自启、时间同步、正式拧紧作业记录、扭矩、合格判定和电机控制仍未验收。
