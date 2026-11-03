# NInfer Live Panel

[English](./README.en.md) | 中文

只读实时面板：看一台已经在跑的 NInfer，不部署、不下载、不启动任何推理框架。

- **只 GET，不 POST**：轮询 `/health`、`/v1/load`、`/stats`、`/metrics`、`/slots`，不聊天、不生成、不加载、不卸载模型、不改 NInfer 配置。NInfer 离线时面板只显示离线，不会替你把它拉起来。
- **镜像**：`ghcr.io/izerok/ninfer-live-panel:latest`（本仓库 push 到 main 后由 GitHub Actions 自动构建推送）。

## 效果图

下图是本面板的真实界面（深色主题、中文界面），数据是模拟 NInfer，不是真实 ninfer-unc 的遥测：模型名带 `(DEMO)`，GPU / CPU / 磁盘卡片显示“不可用”是因为截图环境没有挂载显卡工具和宿主 `/proc`。

主面板（单位已按 v0.1.1 规则显示：`tok/s`、`12K`、`180K / 524.3K`、`1h 00m`）：

![主面板](docs/screenshots/panel.png)

设置弹窗（右上角“设置”打开，改 NInfer 地址不用改 compose）：

![设置弹窗](docs/screenshots/settings.png)

历史曲线多维度（解码 + 预填充 + KV 占用 + GPU 负载同开，左轴 tok/s、右轴 %）：

![历史曲线多维度](docs/screenshots/history.png)

## 快速开始

```bash
docker compose up -d
```

打开 http://127.0.0.1:8091/ 。面板默认只发布到宿主回环地址，不要改成 `0.0.0.0` 对外发布（见[安全](#安全)）。

也可以不用 compose，直接拉镜像跑：

```bash
docker run -d --name ninfer-panel -p 127.0.0.1:8091:8091 \
  -v ninfer-panel-data:/app/data \
  ghcr.io/izerok/ninfer-live-panel:latest
```

从源码跑（只要 Python 3.12，无第三方依赖）：

```bash
python3 app.py
```

## 界面一览

| 区域 | 内容 |
| --- | --- |
| 模型状态 | 五态：空闲 / 正在读取 / 正在生成 / 排队中 / 错误。NInfer 没有单一状态字段，这是面板按 running / waiting / prefilling / decode_ready 的公开映射，不是服务端原样字段。 |
| 8 张指标卡 | 解码与预填充速度、GPU 负载、显存、GPU 温度、功率、PCIe 链路、CPU、磁盘读取。卡片下是最近 60 秒的迷你曲线（页面级，刷新会丢，见历史曲线）。 |
| 历史曲线 | 解码、预填充、KV 占用、GPU 负载四条曲线，维度图例可多选（选择记在浏览器里）；时间可切 15 分钟 / 1 小时 / 24 小时，点时间立即重新拉取，横轴按所选窗口画；悬停看某时刻各维度数值。左轴是 tok/s，右轴是 %（只选 % 维度时左轴也显示 %）。 |
| 当前请求 | 当前处理中的 slot 逐条列出：slot 号、prompt 长度、缓存复用、上下文窗口、占窗口比例。 |
| 上下文占用 | 窗口上限（`/v1/load` 的 `capacity.max_context`）、KV 缓存占用、系统内存、GPU 温度。 |
| 对话缓存 | 保留的 slot 数与宿主 KV，以及累计复用 token 数。 |

## 设置：NInfer 地址在界面里改

compose 里**不写死** NInfer 地址。点右上角“设置”按钮打开弹窗，在里面填地址（例如 `http://host.docker.internal:8080`，或同网容器名 `http://ninfer-unc:8080`），点保存立即生效，不用改 compose、不用重启面板；弹窗点遮罩、按 Esc 或点 × 都能关。

优先级：**界面保存的地址 > `NINFER_BASE_URL` 环境变量 > 镜像默认地址**。保存的值写在数据卷的 `settings.json` 里，刷新、重启、重建容器都不会丢；不用数据卷时，文件只在容器层里，刷新和重启不丢、重建会丢。

## 历史曲线为什么刷新不丢

旧版迷你曲线只存在浏览器内存里，刷新页面就没了。现在历史曲线由后端每 2 秒采样一次，写盘保存在数据卷的 `history.jsonl` 里：刷新页面、重启容器、重建容器（只要挂了数据卷）都不会丢，面板重启后从盘里续上。只保留最近 24 小时，超过的自动清理。

曲线里只有聚合速度（解码 / 预填充 tok/s、KV 占用、GPU 负载），不含任何提示词或生成内容。

## 深浅色与多语言

- 右上角按钮切深色 / 浅色：没手动选过时跟随系统，选过一次后记在浏览器 `localStorage` 里。
- 右上角语言选择框切中文 / English：同样记在 `localStorage` 里；没选过时按浏览器语言判断（中文进中文，其他进英文）。界面文案全部来自前端一本字典，不引任何外部语言包。
- 加一种语言：在 `web/i18n.js` 的 `I18N` 字典里加一节，并在语言选择框里加一个 option；缺失的 key 会回退中文。**`web/index.html` 里不放任何界面文案**：所有可见文字和 aria-label 都由 `data-i18n` / `data-i18n-aria` 从 `i18n.js` 填充，改文案只改 `i18n.js`。

## 数据来源与口径

| 接口 | 用来显示什么 |
| --- | --- |
| `/health` | 在线与否、版本号 |
| `/v1/load` | 模型、运行时间、容量、admitted / running / waiting / prefilling / decode_ready、KV 占用、累计 prefill / decode 计数 |
| `/stats` | 累计均值、队列深度、历史峰值接纳 |
| `/metrics` | 请求完成 / 失败 / 拒绝、KV 占用率、草稿接受率、累计均值速度 |
| `/slots` | slot 总数、处理中、保留数；处理中 slot 的 prompt 长度与缓存复用部分 |
| `nvidia-smi` | GPU 负载、显存、温度、功率（需宿主装 nvidia-container-toolkit 并直通 GPU，否则卡片明说不可用） |
| 宿主 `/proc`（只读挂载） | 系统内存、CPU、磁盘吞吐（不挂载时明说不可用，绝不用容器自己的数字冒充宿主） |

两种速度要分清：

- **瞬时速度**：后端每 2 秒取一次累计计数，用（本次 − 上次）/ 间隔算出，页面上标明了。
- **近 15 分钟均值**：后端把计数采样留 900 秒，现算窗口内均值；不满 15 分钟时卡片写实际窗口时长，不拿累计均值冒充它。
- **累计均值**：NInfer `/metrics` / `/stats` 自带的从启动算起的平均值，单独列出。

## 不造数的清单

Strata 有、NInfer 没有的字段，本面板一律不编：

- **单请求进度**：NInfer `/slots` 不报告，进度条在生成 / 读取时只做进行中动画，不填假百分比。
- **历史请求**：NInfer 不提供历史接口，所以没有“最近请求”表；只有“当前请求”表，列的是此刻处理中的 slot。排队请求也只有个数，没有逐条明细。
- **显存中的专家**：这是 Strata 的 MoE 专家缓存，NInfer 没有，上下文栏改用 NInfer 的 KV 缓存。
- **PCIe 传输速率**：NInfer 不报告，`nvidia-smi` 单次查询也只给链路代宽，PCIe 卡只显示链路，传输速率写“未报告”。
- **已生成 token 数**：`/slots` 没有，所以当前请求表只有 prompt 长度，没有输出 token 数。
- **采集未通的字段**：显示“不可用”，不显示 0（0 会被误读成实测值）。

## 数字显示规则（只改显示，不改数值）

- 速度单位一律写 `tok/s`，不缩写成 `t/s`；≥ 1000 tok/s 缩成 `k tok/s`（如 1.23k tok/s）。
- token 数 ≥ 1000 缩成 K/M（如 12.0K、262K、180K / 524K），精确值保留在悬停提示和 `/api/snapshot` 原始数字里。
- 字节自动换档 B / KB / MB / GB（如 512 MB / 1.00 GB，不用 0.50 GB）；≥ 1024 MB/s 自动升 GB/s。
- 百分比统一 1 位小数；运行时间显示为 `1h 00m` / `45m` / `30s`，不显示裸秒数；温度、功率单位不变。

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `NINFER_BASE_URL` | `http://host.docker.internal:8080` | 首次运行的 NInfer 地址；界面保存过地址后不再用它 |
| `NINFER_API_KEY` | 空 | 仅当 NInfer 设了 API key 时填，后端以 Bearer 发给读取口，绝不放进快照或前端 |
| `PANEL_BIND` / `PANEL_PORT` | `0.0.0.0` / `8091` | 容器内监听地址与端口；对外发布靠 compose 的 `127.0.0.1:8091:8091` 控制 |
| `POLL_INTERVAL` | `2` | 后端轮询间隔（秒） |
| `PANEL_HISTORY_FILE` | `/app/data/history.jsonl` | 历史曲线落盘文件 |
| `PANEL_SETTINGS_FILE` | `/app/data/settings.json` | 界面保存的地址文件 |
| `PANEL_UPDATE_CHECK` | `1` | 设为 `0` 关闭升级检查（离线主机用） |
| `VERSION`（文件，非环境变量） | 仓库根目录 | 当前版本号，镜像标签和 Release 标签都从它来 |

## 版本、升级检查与发布流程

- **版本号**：仓库根目录的 `VERSION` 文件就是当前版本（例如 `0.1.0`），面板右上角会显示它，镜像同时打 `:latest` 和 `:v0.1.0` 两个标签。
- **升级检查**：面板每小时（缓存 1 小时）向 GitHub 公开 Releases 接口查一次本仓库的最新 Release，只读公开记录，不发 token、不发面板数据、不上报；查不到或失败时升级横幅保持隐藏，不报错。发现新版本时顶部出现横幅，点链接去看 Release。完全离线的主机可设 `PANEL_UPDATE_CHECK=0` 关掉它。
- **改动流程**：`main` 分支受保护，不直接推 main。改动走正常 PR：开分支 → 推分支 → 开 PR → 至少 1 人 approve + `build-and-push` 检查通过 → 合并。合并到 main 后 Docker Publish 自动构建推镜像，构建成功后 Release 工作流自动发 Release（VERSION 没变就不重复发）。

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

## 版式来源

界面版式按 Niko1221/Strata 的 `apps/host` Monitor 屏复刻（Strata 为 MIT 许可），数据源换成本地 NInfer。本项目与 Strata、NInfer 官方均无隶属关系。

## 开发

```bash
# 改前端后直接刷新页面即可（静态页由 app.py 现读现发）
# 改后端后重启 app.py；语法检查：
python3 -m py_compile app.py
```

真机联调仍待做：在 NInfer 所在宿主上跑起来，看到模型名、运行时间、瞬时速度随一次真实请求起伏，才算闭环。
