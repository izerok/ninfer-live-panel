# NInfer Live Panel

[English](./README.en.md) | 中文

只读实时面板：看一台已经在跑的 NInfer，不部署、不下载、不启动任何推理框架。

- **只 GET，不 POST**：轮询 `/health`、`/v1/load`、`/stats`、`/metrics`、`/slots`，不聊天、不生成、不加载、不卸载、不改配置。NInfer 离线时只显示离线，不会替你把它拉起来。
- **镜像**：`ghcr.io/izerok/ninfer-live-panel:latest`（push 到 main 后由 GitHub Actions 自动构建推送）。

## 效果图

下图是真实界面（浅色主题、中文界面），数据是模拟 NInfer，不是真实 ninfer-unc 的遥测：模型名带 `(FAKE)`，CPU / 磁盘卡片显示“不可用”是因为截图环境没有挂载宿主 `/proc`。

主面板（9 张指标卡，PCIe 卡可在设置里隐藏；当前请求表上半是进行中的请求，下半灰色行是过去 1 小时内观测到的已结束请求）：

![主面板](docs/screenshots/panel.png)

设置弹窗（右上角“设置”打开，改 NInfer 地址不用改 compose）：

![设置弹窗](docs/screenshots/settings.png)

历史曲线多维度（默认 15 分钟；解码 + 预填充 + KV 占用 + GPU 负载同开，图例带最新值，左轴 tok/s、右轴 %）：

![历史曲线多维度](docs/screenshots/history.png)

## 快速开始

```bash
docker compose up -d
```

打开 http://127.0.0.1:8091/ 。面板默认只发布到宿主回环地址，不要改成 `0.0.0.0` 对外发布（见[安全](#安全)）。

```bash
# 不用 compose，直接拉镜像跑：
docker run -d --name ninfer-panel -p 127.0.0.1:8091:8091 \
  -v ninfer-panel-data:/app/data \
  ghcr.io/izerok/ninfer-live-panel:latest

# 从源码跑（只要 Python 3.12，无第三方依赖）：
python3 app.py
```

## 界面一览

| 区域 | 内容 |
| --- | --- |
| 模型状态 | 五态：空闲 / 正在读取 / 正在生成 / 排队中 / 错误。NInfer 没有单一状态字段，这是面板按 running / waiting / prefilling / decode_ready 的公开映射。 |
| 9 张指标卡 | 解码速度、预填充速度、GPU 负载、显存、GPU 温度、功率、PCIe 链路、CPU、磁盘读取。每张卡下是迷你曲线，刷新页面后从后端历史续上（PCIe 只有链路信息，曲线恒为虚线）。PCIe 卡可在设置里勾选隐藏（默认显示，隐藏只影响本浏览器视图，轮询不停）。 |
| 当前请求 | 上半是当前处理中的 slot：slot 号、prompt 长度、缓存复用（长度 · 占 prompt 比例，如 4K · 33.3%）、上下文窗口、占窗口比例、状态“进行中”。下半灰色行是面板过去 1 小时内观测到的已结束请求（状态“已结束 HH:MM”），只含长度不含内容；slot 号会复用，同一编号可能出现两次。排队请求只有个数，没有逐条明细。 |
| 上下文占用 | 最长处理中 prompt / 窗口上限（`/v1/load` 的 `capacity.max_context`），另有 KV 缓存、系统内存、GPU 温度三条。 |
| 对话缓存 | 保留的 slot 数与宿主 KV，以及累计复用 token 数。 |
| 历史曲线 | 解码、预填充、KV 占用、GPU 负载四条曲线，图例可多选（选择记在浏览器里），图例带各维最新值；默认 15 分钟，时间切 15 分钟 / 1 小时 / 24 小时（保留时长够 7 天时多一个 7 天档），悬停看某时刻数值，下方有当前窗口的平均/峰值统计，右上角“导出 CSV”。曲线由后端每 2 秒采样、写盘保存，刷新、重启、重建（挂数据卷时）都不丢，只保留最近 24 小时（保留时长可配）；数据跨度不足所选窗口时横轴贴合数据跨度，曲线始终铺满，横轴刻度按跨度自适应。 |
| 状态事件 | 后端轮询到的状态变化日志（时间、旧状态→新状态、原因），最多 200 条，存在数据卷里；曲线上对应时刻有竖线标记（离线红、恢复绿、其他灰）。 |

## 设置

右上角“设置”弹窗改 NInfer 地址，保存立即生效，不用改 compose、不用重启。优先级：**界面保存的地址 > `NINFER_BASE_URL` 环境变量 > 镜像默认地址**。弹窗里还能“测试连接”（只查 `/health`，不发 API key、不自动保存）、调页面刷新间隔（1–10 秒，只影响页面，后端采样不变）、手动“检查更新”（绕过 1 小时缓存）、开“离线时发浏览器通知”（默认关）、勾“隐藏 PCIe 卡片”（默认不勾，只影响本浏览器视图）。保存的值写在数据卷的 `settings.json` 里。

右上角按钮切深色 / 浅色、切中文 / English，选择都记在浏览器 `localStorage` 里；没选过时主题跟随系统、语言按浏览器语言判断。界面文案全部来自 `web/i18n.js` 一本字典，`web/index.html` 里不放任何界面文案。

## 数据来源与口径

| 接口 | 用来显示什么 |
| --- | --- |
| `/health` | 在线与否、版本号 |
| `/v1/load` | 模型、运行时间、容量、admitted / running / waiting / prefilling / decode_ready、KV 占用、累计计数 |
| `/stats` | 累计均值、队列深度、历史峰值接纳 |
| `/metrics` | 请求完成 / 失败 / 拒绝、KV 占用率、草稿接受率、累计均值速度 |
| `/slots` | slot 总数、处理中、保留数；处理中 slot 的 prompt 长度与缓存复用部分 |
| `nvidia-smi` | GPU 负载、显存、温度、功率（需宿主装 nvidia-container-toolkit 并直通 GPU，否则明说不可用） |
| 宿主 `/proc`（只读挂载） | 系统内存、CPU、磁盘吞吐（不挂载时明说不可用，绝不用容器自己的数字冒充宿主） |

三种速度要分清：**瞬时速度**是后端每 2 秒取累计计数算的（本次 − 上次）/ 间隔；**近 15 分钟均值**是后端留 900 秒采样现算的窗口均值；**累计均值**是 NInfer `/metrics` / `/stats` 自带的从启动算起的平均值。

## 不造数的清单

Strata 有、NInfer 没有的字段，本面板一律不编：

- **单请求进度**：`/slots` 不报告，进度条在生成 / 读取时只做进行中动画，不填假百分比。
- **历史请求**：NInfer 不提供历史接口，表里的过去行是面板自己轮询 `/slots` 观测到的过去 1 小时记录，不是原生历史；面板启动前、停机期间的请求不存在，不补。
- **显存中的专家**：Strata 的 MoE 专家缓存，NInfer 没有，上下文栏改用 KV 缓存。
- **PCIe 传输速率**：NInfer 不报告，`nvidia-smi` 单次查询也只给链路代宽，PCIe 卡只显示链路，传输速率写“未报告”。
- **已生成 token 数**：`/slots` 没有，当前请求表只有 prompt 长度，没有输出 token 数。
- **采集未通的字段**：显示“不可用”，不显示 0（0 会被误读成实测值）。

## 数字显示规则（只改显示，不改数值）

- 速度一律写 `tok/s`（不缩成 `t/s`）；解码 ≥ 1000 tok/s 缩成 `k tok/s`（如 1.23k tok/s），预填充一律原数不缩 k（如 1245.3 tok/s）。
- 缓存复用列写“长度 · 占 prompt 比例”（如 4K · 33.3%）。
- token 数 ≥ 1000 缩成 K/M（如 12K、262.1K、180K / 524.3K），精确值在悬停提示和 `/api/snapshot` 原始数字里。
- 字节自动换档 B / KB / MB / GB；≥ 1024 MB/s 自动升 GB/s；百分比统一 1 位小数；运行时间显示为 `1h 00m` / `45m` / `30s`。

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `NINFER_BASE_URL` | `http://host.docker.internal:8080` | 首次运行的 NInfer 地址；界面保存过地址后不再用它 |
| `NINFER_API_KEY` | 空 | 仅当 NInfer 设了 API key 时填，后端以 Bearer 发给读取口，绝不放进快照或前端 |
| `PANEL_BIND` / `PANEL_PORT` | `0.0.0.0` / `8091` | 容器内监听地址与端口；对外发布靠 compose 的 `127.0.0.1:8091:8091` 控制 |
| `POLL_INTERVAL` | `2` | 后端轮询间隔（秒） |
| `PANEL_HISTORY_FILE` | `/app/data/history.jsonl` | 历史曲线落盘文件；事件（`events.jsonl`）、请求记录（`requests.json`）、设置（`settings.json`）都在同一目录 |
| `PANEL_HISTORY_RETENTION_SECONDS` | `86400` | 历史保留时长（秒）；历史时间档上限跟它走，设 604800 才有 7 天档 |
| `PANEL_UPDATE_CHECK` | `1` | 设为 `0` 关闭升级检查（离线主机用） |
| `VERSION`（文件） | 仓库根目录 | 当前版本号，镜像标签和 Release 标签都从它来 |

## 版本、升级检查与发布流程

- 面板右上角显示 `VERSION` 文件的版本；镜像同时打 `:latest` 和 `:v<VERSION>` 两个标签。
- 升级检查：面板每小时（缓存 1 小时）向 GitHub 公开 Releases 接口查一次本仓库的最新 Release，只读公开记录，不发 token、不发面板数据；查不到或失败时横幅保持隐藏，不报错；发现新版本时顶部出现横幅，点链接去看 Release。
- 改动流程：`main` 分支受保护，不直接推 main。改动走正常 PR：开分支 → 推分支 → 开 PR → 至少 1 人 approve + `build-and-push` 检查通过 → 合并。合并到 main 后 Docker Publish 自动构建推镜像，构建成功后 Release 工作流自动发 Release（VERSION 没变就不重复发）。

## 安全

完整说明见 [SECURITY.md](./SECURITY.md)。要点：

- `/api/snapshot` 本身无鉴权，能打开 8091 就能看到模型名、请求计数、GPU 与宿主指标、处理中请求的 prompt **长度**（仅长度，不是内容）。所以默认只发回环地址；对外发布前必须在前面放自己控制的、带鉴权的反向代理，只加 TLS 不等于加鉴权。
- 容器内以非 root（uid/gid 10001）运行，无特权、无宿主网络、无 Docker socket 挂载。
- GitHub Actions 工作流只用仓库自带的 `GITHUB_TOKEN` 登录 GHCR，权限收紧为 `contents: read` + `packages: write`，不向日志输出密钥。

## 排障

| 现象 | 先查什么 |
| --- | --- |
| 面板开但全是离线 | 先确认 NInfer 在跑、`curl http://127.0.0.1:8080/health` 在宿主上有返回，再核对面板“设置”里的地址 |
| GPU 卡片说不可用 | 宿主没装 nvidia-container-toolkit，或 compose 里删了 GPU 直通段；删了也能看 NInfer 数字，只是没有 GPU 卡 |
| 系统内存说不可用 | 没挂载宿主 `/proc`；compose 默认挂了 `/proc:/host/proc:ro`，删掉它内存就是不可用，不会用容器内存顶替 |
| 瞬时速度偶尔为 0 但状态是生成中 | 两次采样之间刚好没有新提交 token，是真实现象；看累计均值和曲线一起判断 |
| 历史曲线是空的 | 刚启动不满两次采样时正常；超过一分钟还空，检查数据卷是否挂载、面板日志有无写盘报错（写盘失败时曲线退回内存模式，不影响主面板） |

## 版式来源与开发

界面版式按 Niko1221/Strata 的 `apps/host` Monitor 屏复刻（Strata 为 MIT 许可），数据源换成本地 NInfer。本项目与 Strata、NInfer 官方均无隶属关系。

```bash
# 改前端后直接刷新页面即可（静态页由 app.py 现读现发）
# 改后端后重启 app.py；语法检查：
python3 -m py_compile app.py
```

真机联调仍待做：在 NInfer 所在宿主上跑起来，看到模型名、运行时间、瞬时速度随一次真实请求起伏，才算闭环。
