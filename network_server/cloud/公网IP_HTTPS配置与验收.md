---
title: 腾讯云公网 IP HTTPS：部署准备与验收
date: 2026-10-01
tags: [腾讯云, HTTPS, Nginx, Certbot, 嵌入式, 验收]
status: 云端软件与ACME配置准备通过，未签发证书，未开放公网设备页面
---

# 腾讯云公网 IP HTTPS

## 当前事实与上线边界

- 用户云端实测：Ubuntu 20.04 / Python 3.8.10，后端 `tencent-observations.service` active；80/443 无监听，Nginx/Snap 均未安装；UFW active，目前仅放行原 SSH、MQTT 与 MediaMTX 相关端口。
- 当前目标 IP `118.25.40.152`，上海节点，无域名。外部 80/443 探测超时，不据此判断云防火墙的具体规则。
- Let's Encrypt 支持 IP 地址证书，必须采用 shortlived profile，有效 160 小时；Certbot webroot 需要 5.4 或更新版本。不能用 Ubuntu 20.04 旧 apt Certbot 或直接假定 nginx 插件支持 IP。
- **技术支持 IP 证书不等于允许免备案公开网站。** 腾讯云中国内地网站/APP 的公开服务有备案要求。应向腾讯云工单确认该上海节点、无域名、API 鉴权私有仪表盘的访问方式是否获准；未确认前只准备软件/配置，不开放 80/443。不通过改端口、隐藏域名或 IP 访问绕过要求。
- 若提供商要求域名备案，需完成备案或用户另行选择合规的部署节点；本包固定现有 IP，不能直接拿去部署新 IP。

官方来源（2026-10-01 核对）：[IP 证书发布](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability/)、[Certbot IP 签发与续期](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)、[Certbot 安装](https://certbot.eff.org/instructions?ws=nginx&os=snap)、[腾讯云备案概述](https://cloud.tencent.com/document/product/243/18907)。

## 结构与安全边界

```text
浏览器 HTTPS 443 → Nginx（仅 GET/HEAD）→ 127.0.0.1:18088 云端后端
ESP32 原上传 → 鲁班猫原 SSH 隧道 → 同一个云端后端
```

仅增加浏览器公网查看入口。原 SQLite 数据、API token、后端服务、上传路径和电机安全状态不改。公网 POST 等写请求在 Nginx 拒绝；读数据仍由后端 Bearer token 鉴权。没有远程 START。

初始 HTTP 80 仅提供 ACME challenge，其他路径返回 404。最终 HTTPS 启用后 HTTP 页面请求转到固定 IP 的 HTTPS，不在 HTTP 显示密钥输入页。不开放后端 18088、Modbus 502、鲁班猫 18089。TLS 1.2/1.3，限流/限连接和请求体限制，关闭访问日志；用户不把 token 放 URL、截图或聊天。

## 部署包：默认检查，不自动上线

本机文件 `network_server/cloud/tencent-ip-https-20261001.zip`，只含代码、配置和续期 hook，不含 API token、Wi-Fi 密码、证书私钥或数据库。上传至**腾讯云** `/root`，不是鲁班猫。

部署包大小 6476 B，SHA256 `52574B6D87639CD545A0A0A5FFBF100BECBF1034FC6221BC1F10EA5D38A437B8`；本次版本核对值，不用于其他版本。

```bash
# 默认只读检查
python3 /root/tencent-ip-https-20261001.zip
# 软件与 ACME-only 配置准备；不会放行防火墙或公开页面
python3 /root/tencent-ip-https-20261001.zip --prepare
```

`--prepare` 安装 Nginx、Snapd、CA/curl 和官方 Snap Certbot；验证版本至少 5.4。初始 Nginx 不应已存在；若存在则拒绝覆盖。仅禁用本次新装 Nginx 的默认站点链接，并在 `/var/lib/tightening-ip-https/default-site.before` 保留它。UFW 必须默认阻挡入站，不接受已有 Web 放行或宽泛放行规则。对软件源不可达、Snap 失败或 nginx 配置错误，停止并保留现场，不反复运行初始化包。

软件安装会添加系统依赖和服务，**不是无状态检查**。不升级操作系统、不改 SSH、MQTT、视频服务或既有 UFW 规则；初始 UFW 继续阻挡 Web 端口。尚未云端执行，不宣称安装或 nginx -t 已通过。

## 仅在提供商确认允许后：验证公网 80

在腾讯云实例防火墙放行 TCP 80；保留所有原有规则。HTTP-01 验证必须由公网访问到 TCP 80，不能只从服务器 curl localhost 来证明。

```bash
ufw allow proto tcp from 0.0.0.0/0 to any port 80 comment 'tightening ACME challenge'
```

此时仍只提供 challenge，不提供设备数据。通过创建无秘密随机 challenge 测试文件，从独立网络访问其 URL 确认内容完全一致。若返回提供商拦截页或超时，停止，不通过其他端口绕过；核对云防火墙、UFW、路由及提供商要求。

## 交互式签发：先测试，再正式

账户邮件和 ACME 条款由用户在云端本地交互填写/确认，不放聊天；不替用户自动接受条款。

```bash
# 测试证书不受浏览器信任，不能用于正式页面。
/snap/bin/certbot certonly --staging --preferred-profile shortlived --webroot --webroot-path /var/www/tightening-acme --ip-address 118.25.40.152 --cert-name tightening-ip-test
# 测试成功后申请正式可信证书，名称固定。
/snap/bin/certbot certonly --preferred-profile shortlived --webroot --webroot-path /var/www/tightening-acme --ip-address 118.25.40.152 --cert-name tightening-public-ip
```

不使用 `--nginx` 获取 IP 证书，不关闭证书校验。证书在 `/etc/letsencrypt/live/tightening-public-ip/`，私钥不导出、不截图。公网 IP 改变后必须重新规划证书与配置。

## HTTPS 激活与续期验收

只有已确认提供商政策并取得正式证书后，才执行：

```bash
python3 /root/tencent-ip-https-20261001.zip --activate --provider-policy-confirmed
```

激活先验证系统 CA 信任链、IP SAN、剩余寿命至少一天；测试证书、错 IP 或过期证书不能激活。OpenSSL 的 `-checkip` 不仅检查进程退出码，还核对明确的匹配结果。仅替换本包的精确 HTTP 配置，保留快照；拒绝改写其他站点。

随后 nginx -t → reload → 本机 TLS 验证（不使用 curl -k）→ /health 控制锁定 → POST 403 → 无密钥数据 GET 401。成功后启用每 6 小时的续期 timer，并仅为 IPv4 TCP 443 添加 UFW 规则；还需用户在腾讯云防火墙放行 443。失败退回 ACME-only 配置，保留生成文件待定位；没有重启后端或回退数据库。

续期 reload hook 放入 Certbot 持久的 `renewal-hooks/deploy`，同时适用于 Snap 自带 timer 和本包 timer。若只在自定义 timer 的命令行放 hook，自带 timer 先续期时 Nginx 可能继续持有旧证书，这是短证书必须避免的问题。

```bash
/snap/bin/certbot renew --cert-name tightening-public-ip --dry-run --run-deploy-hooks
systemctl is-active tightening-ip-cert-renew.timer
systemctl is-enabled tightening-ip-cert-renew.timer
systemctl list-timers tightening-ip-cert-renew.timer
```

从独立网络打开 `https://118.25.40.152/`，浏览器应无证书警告，先不给 token 验证数据请求 401，再在页面本地输入现有 API token，核对真实样本继续增加。验证公开 POST 被拒绝、原 ESP32 uploaded 继续增长/缓存清空、SSH/MQTT/视频服务未变。证书链、本机 TLS、外部访问、dry-run 和正常周期的真实续期是不同证据，不能互相替代。

## 当前验收状态

本轮只完成云端前置检查和本地部署包/配置准备。未安装云端 Nginx/Certbot，未放行防火墙，未签发证书，未激活公网，未验证真实续期。电机控制仍锁定，不因配置网站而重启 STM32。

本地新增 8 项部署安全测试通过；ESP-IDF Python 环境全部 33 项服务器/配网/探针/部署回归通过，无跳过；部署脚本 Python 3.8 AST 兼容检查及 ZIP 入口/资产核对通过。这些不替代目标机 nginx -t、实际签发与外部 TLS 验收。系统 Python 3.13 首轮全量测试有一次既有 HTTP 拒绝测试 WinError 10053 且 NVS 测试因缺 ESP-IDF 跳过；未改变服务器逻辑，换回项目 ESP-IDF 环境后上述全量通过，不据此认定所有 Python 环境问题已定位。

### 云端准备完成：用户终端回传（2026-10-01 21:56 后）

用户执行 `--prepare` 后回传日志：Nginx 1.18.0 Ubuntu 软件包与 Snapd 安装完成，`nginx -t` 成功，Nginx 服务启用；Snap 安装 core24 与官方 Certbot 5.8.0，最后明确输出 `PREPARE PASS`。这覆盖前文“未安装云端软件”的历史状态，但不是助手直接登录云端复核。

根据脚本及用户输出，本阶段只配置 HTTP ACME challenge，其他 HTTP 路径 404；没有放行防火墙、没有公开设备页面、没有重启后端或读取 API token。`snapd.failure.service` 等 disabled/static 提示不是本次失败，后续 Certbot 安装和 PREPARE PASS 已完成。

当前尚未确认提供商允许该上海节点的无域名私有仪表盘公网访问；未执行公网 80 验证、证书签发、HTTPS 激活或续期 dry-run。不要重复执行 `--prepare`，它会为保护既有配置拒绝重跑。下一步先确认提供商要求，再进行定向放行和正式签发，不改现有上传链路。
