# Docker 与 clang-format（2026-10-06）

## 当前状态

已配置 Dockerfile、默认拒绝的构建上下文过滤、非 root 编译入口，以及 clang-format。
本机找到并实际使用 clang-format 21.1.3；没有找到 Docker 引擎，**尚未构建或运行容器**。
ARM、ESP32 和主机测试目前仍由本机工具链验证，不能把它说成 Docker 验收通过。

## 格式化

在 `D:\new project` 执行：

```powershell
python tools/format_code.py           # 只检查
python tools/format_code.py --write   # 格式化明确列出的文件
```

规则在 `.clang-format`，范围在 `tools/format_scope.txt`。目前先统一新 Transfer 模块和测试的
10 个文件，不整批改写旧 main.c、Cube/驱动库、Pigweed、生成代码或私有配置。
VSCode 已有推荐扩展和格式规则；默认未打开“保存即格式化”，避免无意改动生成文件。
可用 `--clang-format 路径` 指定自己的工具。容器使用 clang-format-18；跨版本输出尚未实测。

## Docker 编译

安装并启动 Docker 后，从项目根目录执行：

```powershell
docker build -t tightening-build:local .
New-Item -ItemType Directory -Path container_artifacts -Force
docker run --rm --network none --mount "type=bind,source=$((Get-Location).Path)\container_artifacts,target=/out" tightening-build:local --slot both --preset RouterTransferSamplingReadOnly --host-tests --format-check
```

只挂载输出目录，不挂整个工作区。镜像只接收构建所需目录；热点/API 配置、备份、数据库、
波形和密钥不进入上下文。容器不用特权模式、USB、串口、SSH、主机网络；脚本不能刷板。
如果 Linux 的 `/out` 权限不匹配，用宿主 UID/GID 运行，或给专用输出目录配置正确所有权。

Linux apt 工具链和本机 Arm GNU 15.3.1 **不是同一个版本**；该配置解决可复用环境，尚不保证
逐字节可复现。要实现可复现构建，需进一步固定基础镜像摘要、软件源快照及工具链校验和，
并在可用 Docker 引擎中验证。没有下载未知来源的工具链，也没有安装 Docker/WSL 或重启系统。

ESP-IDF 不在这个 ARM/主机测试镜像中。ESP32 继续使用当前已安装的 IDF 环境：

```powershell
./tools/build_router_network.ps1 -Esp32 -Transfer
```

这是仅编译命令，不会改 NVS、分区、固件或复位设备。
