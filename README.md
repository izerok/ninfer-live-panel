# NInfer 实况面板（只看，不部署）

> 本页按 Niko1221/Strata apps/host 的 Monitor 屏 1:1 复刻版式
> （Strata 为 MIT 许可），数据源换成本地 NInfer。
> 版式、卡片顺序、中文文案均照 Strata 的来：
> 模型状态卡（空闲 / 正在读取 / 正在生成 / 排队中 / 错误五态 +
> 模型进度条）→ 8 张指标卡（速度、GPU 负载、显存、GPU 温度、
> 功率、PCIe、CPU、磁盘读取，4 列）→ 上下文占用 + 最近请求 →
> 对话缓存。NInfer 状态映射到 Strata 五态：空闲→空闲，
> 预填充中→正在读取，生成中→正在生成，排队→排队中，离线→错误。
> 注意：截图那块板的 pills 是“预热中 / 生成中”，那不是 Strata
> 的文案；Strata 原文案是“正在读取 / 正在生成”，本页用 Strata 的。

## 适配清单：Strata 有、NInfer 没有的，一律不造数

- **单请求进度**：Strata 的模型进度条是当前请求的 done/total，
  NInfer `/slots` 不报告单请求进度，本页进度条在生成/读取时
  只做进行中动画，不填假百分比。
- **最近请求表**：Strata 列历史请求（时间、状态、Prompt、复用、
  输出、Tok/s、显存命中率、时长），NInfer 不提供历史请求接口，
  本表保持“暂无请求记录”空态，不把当前处理中请求伪装成历史。
- **显存中的专家**：这是 Strata 的 MoE 专家缓存，NInfer 没有，
  上下文占用栏的第一条改用 NInfer 的 KV 缓存。
- **PCIe 传输速率**：NInfer 不报告，nvidia-smi 单次查询也只给
  链路代宽（Gen / x宽），本页 PCIe 卡只显示链路，传输速率写
  “未报告”，不编一个 MB/s。
- **对话缓存**：Strata 的“保留的会话 / 他们的内存”对应到 NInfer
  的 retained slot 数 / 宿主 KV 字节，事实栏用累计复用 tokens。

给本地已经在跑的 NInfer（例如你的 ninfer-unc）做的一个实时面板。
它**不部署、不下载、不启动任何推理框架**，不碰 Strata。
Strata 那个 Docker 包已经按你的意思搁置了，不要再用它来看 NInfer，
它本来就看不到 NInfer。

## 布局：照截图那套来的

顶部是模型状态图例（空闲 / 预热中 / 生成中 / 排队 / 错误五态，
当前态高亮），下面是引擎行，第一排 4 张卡里解码速度和 Prefill
速度是两张独立卡（不是合成一张），第二排是 GPU 负载、显存、
温度/功率、CPU 负载，再加系统内存等卡，最底下是一条状态条
（地址 + 状态 + 数据时间 + 运行时间）。截图里是两个引擎行
（llama.cpp + NInfer），这里只接本地 NInfer，所以只有 NInfer
这一行，不伪造一个没接的 llama.cpp 行。

## 上下文（单独一栏，别跟 KV 混在一起）

- **窗口上限**：`/v1/load` 的 `capacity.max_context`，就是启动时
  的 `--max-context`（你的 ninfer-unc 是 262144）。
- **KV 占用**：设备 KV 缓存已占 tokens / 容量，是缓存池的占用率。
- **状态槽**：设备 / 宿主状态槽已用 / 容量，上下文缓存的槽位。
- **处理中请求的最长 Prompt**：`/slots` 里处理中 slot 的
  `n_prompt_tokens` 取最大，并算它占窗口的百分比；同时列出
  每个处理中 slot 的 prompt 长度和其中缓存复用部分。
  注意：`/slots` 里没有已生成 token 数，所以这里是 prompt
  长度，不是“请求总上下文长度”，页面上就是这么标的。
  KV 占用和 prompt 长度是两回事，不合成一个“上下文已用”。

## 它看什么、从哪来

全部来自 NInfer 自己现成的数据口（源码已核对，不是猜的）：

- `/health`：在不在、版本号
- `/v1/load`：模型、运行时间、容量、admitted / running / waiting /
  prefilling / decode_ready、KV 占用、累计 prefill / decode 计数
- `/stats`：累计均值、队列深度、历史峰值接纳
- `/metrics`（Prometheus 文本）：请求完成/失败/拒绝、KV 占用率、
  草稿接受率、累计均值速度
- `/slots`：slot 总数、处理中、保留数
- `nvidia-smi`：GPU 负载、显存、温度、功率（需要宿主装
  nvidia-container-toolkit 并直通 GPU，否则卡片明说不可用）
- 宿主 `/proc/meminfo`：系统内存（需要把宿主 `/proc` 只读挂载
  进来，否则明说不可用——绝不用容器自己的内存数冒充宿主）

## 两个速度，要分清

- **瞬时速度**：面板后端每 2 秒取一次计数，用
  （本次累计 − 上次累计）/ 间隔算出来。NInfer 自己只给累计
  均值，所以“此刻多少 tok/s”只能这样算，页面上标明了。
- **近 15 分钟均值**：后端把计数采样留 900 秒，现算窗口内
  均值。面板刚启动不满 15 分钟时，卡片会写“近 X 秒/分钟均值”，
  满 15 分钟后才是真正的近 15 分钟均值，不拿累计均值冒充它。
- **累计均值**：NInfer `/metrics` / `/stats` 自带的从启动算起的
  平均值，卡片里单独列出，不跟瞬时、近 15 分钟混在一起。

## 状态怎么来的

NInfer 没有单一状态字段，面板按下面这个公开的映射显示，
不是从服务端原样抄来的：

- 离线：`/health` 不通或非 ok
- 排队：waiting > 0 且 running = 0
- 预热中：prefilling > 0 且 decode_ready = 0
- 生成中：decode_ready > 0 或 running > 0
- 空闲：其余已加载态

## 跑起来

在 NInfer 所在的那台 Ubuntu 宿主上（不是沙箱）：

```bash
cd ninfer-live-panel
docker compose up -d --build
```

打开 http://127.0.0.1:8091/

端口说明：8091 是故意选的——8080 是 NInfer 自己，8090 是你的
nv-power-fan 面板，8787 是之前那个 Strata 面板。面板本身只在
宿主本机露出来，不要改成 `0.0.0.0`。

## 接线：NInfer 在哪，面板就指哪

默认 `NINFER_BASE_URL=http://host.docker.internal:8080`，对应
“NInfer 的 8080 发布在宿主上”这种最常见的情况。compose 里
已经写了 `host-gateway`，Linux Docker 下可用。

- NInfer 是另一个容器、跟面板同网：`.env` 里改成
  `NINFER_BASE_URL=http://ninfer-unc:8080`（服务名以你那边为准）。
- NInfer 设了 API key：`.env` 里填 `NINFER_API_KEY`，面板会在
  需要鉴权的读取口上带 Bearer；`/health` 本身在 NInfer 侧是公开的。
- 面板用 host 网络跑：那就改成 `http://127.0.0.1:8080`，但
  compose 默认不是 host 网络，别两边混着改。

## 排障（先看横幅，它会直说）

- 面板开但全是离线：先确认 ninfer-unc 真的在跑、
  `curl http://127.0.0.1:8080/health` 在宿主上有返回，再核对
  `NINFER_BASE_URL`。面板离线时不会替你把 NInfer 拉起来，
  这是故意的。
- GPU 卡片说 nvidia-smi 不可用：宿主没装 toolkit，或 compose
  里删了 GPU 直通段。删了也能看 NInfer 数字，只是没有 GPU 卡。
- 系统内存说不可用：没挂载宿主 `/proc`。compose 默认挂了
  `/proc:/host/proc:ro`；如果你改了 compose 删掉它，内存就是
  不可用，不会用容器内存顶替。
- 瞬时速度偶尔为 0 但状态是生成中：两次采样之间刚好没有新
  提交 token 时就会这样，是真实现象；看累计均值和曲线一起判断。
- 显存总量、系统内存总量如果显示 0：那不是实测值，是采集
  没通——本面板在这种情况下宁可显示“不可用”，也不显示 0。
  （之前那张小红书截图就是显存共 0GB、系统内存共 0GB，
  属于采集未通，不能信。）

## 它不做什么

不发任何 POST：不聊天、不生成、不加载、不卸载模型，
不改 NInfer 的任何配置。想控制 NInfer，还是走它自己的
API / 容器命令，这个面板只负责看。

## 核实情况

- 源码口径已核：`/v1/load`、`/stats`、`/metrics`、`/slots`、
  `/health` 的字段与上面一一对应，状态映射按
  running / waiting / prefilling / decode_ready 现算。
- 沙箱里没有你的 ninfer-unc、没有 GPU，所以真机联调还没做：
  在宿主上 `docker compose up` 后，打开 8091，看到模型名、
  运行时间、瞬时速度随一次真实请求起伏，才算闭环。
  沙箱里只用模拟 NInfer 验过后端逻辑（计数差分、离线态、
  GPU 不可用时不造假），见 `app.py` 的注释。
