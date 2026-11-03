# NInfer Live Panel

[中文](./README.md) | English

A read-only live panel for an already-running NInfer server. It deploys, downloads, and starts no inference framework.

- **GET only, no POST**: it polls `/health`, `/v1/load`, `/stats`, `/metrics`, and `/slots`. No chat, no generation, no model load/unload, no NInfer configuration changes. If NInfer is offline, the panel just shows offline; it never starts NInfer for you.
- **Image**: `ghcr.io/izerok/ninfer-live-panel:latest` (built and pushed by GitHub Actions on every push to main).

## Screenshots

The images below are the real panel UI (light theme, Chinese UI). The data is simulated, not live ninfer-unc telemetry: the model name carries `(FAKE)`, and the CPU / disk cards show "unavailable" because the screenshot environment had no host `/proc` mount.

Main panel (9 metric cards, the PCIe card can be hidden from Settings; the requests table shows in-flight requests on top and grey rows for requests observed ending in the past hour below):

![Main panel](docs/screenshots/panel.png)

Settings dialog (opened from the top-right Settings button; changing the NInfer address needs no compose edit):

![Settings dialog](docs/screenshots/settings.png)

History with multiple dimensions (15 minutes by default; decode + prefill + KV usage + GPU load together, legend shows latest values, left axis tok/s, right axis %):

![History with multiple dimensions](docs/screenshots/history.png)

## Quick start

```bash
docker compose up -d
```

Open http://127.0.0.1:8091/ . The panel is published to the host loopback only by default; do not change it to `0.0.0.0` for public exposure (see [Security](#security)).

```bash
# Without compose:
docker run -d --name ninfer-panel -p 127.0.0.1:8091:8091 \
  -v ninfer-panel-data:/app/data \
  ghcr.io/izerok/ninfer-live-panel:latest

# From source (Python 3.12, no third-party dependencies):
python3 app.py
```

## What is on screen

| Section | Content |
| --- | --- |
| Model state | Five states: idle / reading / generating / queued / error. NInfer has no single state field; this is the panel's documented mapping from running / waiting / prefilling / decode_ready, not a server field. |
| 9 metric cards | Decode speed, prefill speed, GPU load, VRAM, GPU temperature, power, PCIe link, CPU, disk read. Each card has a sparkline that resumes from backend history after a page refresh (PCIe has link info only, so its sparkline stays dashed). The PCIe card can be hidden from Settings (shown by default; hiding affects only this browser's view, polling continues). |
| Current requests | Top rows are in-flight slots: slot id, prompt length, cached portion (length · share of prompt, e.g. 4K · 33.3%), context window, share of window, status "In flight". Grey rows below are requests the panel observed ending in the past hour (status "Ended HH:MM"); lengths only, no content; slot ids are reused, so one number can appear twice. Queued requests are a count only, with no per-request detail. |
| Context usage | Longest in-flight prompt / window limit (`capacity.max_context` from `/v1/load`), plus KV cache, system memory, and GPU temperature rows. |
| Conversation cache | Retained slot count and host KV, plus cumulative reused tokens. |
| History | Four curves — decode, prefill, KV usage, GPU load — with multi-select dimension toggles in the legend (selection is stored in the browser), and the legend shows each dimension's latest value. The default range is 15 minutes; time range switches between 15 minutes / 1 hour / 24 hours (plus a 7-day range when retention reaches 7 days); hover shows each selected dimension at that moment; below the curve are the current window's average/peak stats, and Export CSV saves the current window and dimensions. The curve is sampled by the backend every 2 seconds and persisted to disk, so it survives page refreshes, restarts, and recreates (with the data volume mounted); only the last 24 hours are kept (retention is configurable). When the data span is shorter than the selected window, the axis fits the data span so the curve always fills the chart, and the time ticks adapt to the span. |
| State events | A log of state changes seen by backend polling (time, old state → new state, reason), capped at 200 entries and stored in the data volume; the curve marks each event's moment with a vertical line (offline red, recovery green, other grey). |

## Settings

The Settings dialog in the top right edits the NInfer address; saving takes effect immediately — no compose edit, no panel restart. Precedence: **UI-saved address > `NINFER_BASE_URL` environment variable > image default**. The dialog also offers Test connection (checks `/health` only, sends no API key, never auto-saves), a page refresh interval (1–10 s, display only — backend sampling is unchanged), a manual Check for updates (bypasses the 1-hour cache), "Notify in browser when offline" (off by default), and "Hide PCIe card" (off by default, affects only this browser's view). The saved value lives in `settings.json` in the data volume.

The top-right buttons switch dark / light and 中文 / English; both choices are stored in browser `localStorage`. Before a choice, the theme follows the system and the language follows the browser language. All UI strings come from one dictionary in `web/i18n.js`; `web/index.html` contains no UI strings at all.

## Data sources and definitions

| Endpoint | Used for |
| --- | --- |
| `/health` | Online or not, version |
| `/v1/load` | Model, uptime, capacity, admitted / running / waiting / prefilling / decode_ready, KV usage, cumulative counts |
| `/stats` | Cumulative averages, queue depth, peak admitted |
| `/metrics` | Requests completed / failed / rejected, KV usage ratio, draft accept rate, cumulative average speeds |
| `/slots` | Slot totals, in-flight and retained counts; in-flight slots' prompt lengths and cached portions |
| `nvidia-smi` | GPU load, VRAM, temperature, power (needs the NVIDIA container toolkit and GPU passthrough on the host; otherwise the cards say unavailable) |
| Host `/proc` (read-only mount) | System memory, CPU, disk throughput (without the mount these say unavailable; the container's own numbers are never substituted) |

Three speeds, kept apart: **instant speed** is (this − last) / interval from cumulative counters sampled every 2 seconds; the **15-minute average** is computed from counter samples kept for 900 seconds; the **cumulative average** is NInfer's own since-startup average from `/metrics` / `/stats`.

## What is deliberately not invented

Fields that exist in Strata but not in NInfer are never fabricated:

- **Per-request progress**: `/slots` does not report it, so the progress bar only animates while reading / generating; it never shows a fake percentage.
- **Request history**: NInfer has no history API, so the grey rows in the table are records the panel itself observed by polling `/slots` in the past hour, not native history; requests from before the panel started or while it was down do not exist and are not backfilled.
- **Experts in VRAM**: a Strata MoE cache concept that NInfer does not have; the context section uses NInfer's KV cache instead.
- **PCIe transfer rate**: not reported by NInfer, and a single `nvidia-smi` query only gives the link generation / width, so the PCIe card shows the link and says the rate is not reported.
- **Generated token counts**: `/slots` has none, so the current-requests table shows prompt length only, not output tokens.
- **Unreachable fields**: shown as "unavailable", never as 0 (0 would be misread as a measured value).

## Number display rules (display only, values unchanged)

- Speed is always written `tok/s`, never abbreviated to `t/s`; decode at or above 1000 tok/s shortens to `k tok/s` (for example 1.23k tok/s), while prefill is always shown raw, never shortened to k (for example 1245.3 tok/s).
- The cached column shows "length · share of prompt" (for example 4K · 33.3%).
- Token counts at or above 1000 shorten to K/M (for example 12K, 262.1K, 180K / 524.3K); the exact value stays in the hover tooltip and in the raw `/api/snapshot` numbers.
- Bytes auto-scale through B / KB / MB / GB; at or above 1024 MB/s the rate switches to GB/s; percentages always show 1 decimal; uptime shows as `1h 00m` / `45m` / `30s`.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `NINFER_BASE_URL` | `http://host.docker.internal:8080` | NInfer address on first run; ignored once an address is saved in the UI |
| `NINFER_API_KEY` | empty | Only if NInfer was started with an API key; the backend sends it as a Bearer token to read endpoints and never puts it in a snapshot or the frontend |
| `PANEL_BIND` / `PANEL_PORT` | `0.0.0.0` / `8091` | In-container listen address and port; public exposure is controlled by compose's `127.0.0.1:8091:8091` mapping |
| `POLL_INTERVAL` | `2` | Backend poll interval in seconds |
| `PANEL_HISTORY_FILE` | `/app/data/history.jsonl` | History curve file; events (`events.jsonl`), request records (`requests.json`), and settings (`settings.json`) live in the same directory |
| `PANEL_HISTORY_RETENTION_SECONDS` | `86400` | History retention in seconds; the history range cap follows it — set 604800 for the 7-day range |
| `PANEL_UPDATE_CHECK` | `1` | Set to `0` to disable the upgrade check (offline hosts) |
| `VERSION` (file) | repo root | Current version; image and Release tags both come from it |

## Version, upgrade check, and release flow

- The panel header shows the `VERSION` file's version; the image is tagged both `:latest` and `:v<VERSION>`.
- Upgrade check: once an hour (cached for 1 hour) the panel asks the public GitHub Releases API for this repository's latest release. It reads a public record only — no token, no panel data. If the check fails, the banner simply stays hidden. When a newer release exists, a banner appears at the top with a link to the Release.
- Change flow: `main` is protected; nothing is pushed to it directly. Changes go through a normal PR: branch → push branch → open PR → at least 1 approval + the `build-and-push` check passing → merge. After merging to main, Docker Publish builds and pushes the image, and on a successful build the Release workflow creates a Release automatically (skipped when `VERSION` did not change, so no duplicate releases).

## Security

See [SECURITY.md](./SECURITY.md) for the full statement. The essentials:

- `/api/snapshot` has no authentication: anyone who can open port 8091 can see the model name, request counts, GPU and host metrics, and in-flight requests' prompt **lengths** (lengths only, not content). That is why the default publish is loopback-only; before exposing it publicly, put an authenticated reverse proxy of your own in front. TLS alone is not authentication.
- Inside the container the panel runs as non-root (uid/gid 10001), with no privileges, no host networking, and no Docker socket mount.
- The GitHub Actions workflow logs in to GHCR with the repository's own `GITHUB_TOKEN` only, with permissions narrowed to `contents: read` + `packages: write`, and prints no secrets to logs.

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| Panel opens but everything is offline | Confirm NInfer is running and `curl http://127.0.0.1:8080/health` answers on the host, then check the address in the panel's Settings card |
| GPU cards say unavailable | The host lacks the NVIDIA container toolkit, or the GPU passthrough block was removed from compose; NInfer numbers still work without it, just without GPU cards |
| System memory says unavailable | Host `/proc` is not mounted; compose mounts `/proc:/host/proc:ro` by default, and removing it makes memory unavailable rather than substituted with container memory |
| Instant speed is occasionally 0 while generating | No new tokens were committed between two samples; this is real behavior — judge it together with the cumulative average and the curve |
| History curve is empty | Normal for the first two samples after startup; if it is still empty after a minute, check that the data volume is mounted and look for write errors in the panel log (a write failure falls back to memory-only history and does not break the main panel) |

## Layout source and development

The layout replicates the `apps/host` Monitor screen of Niko1221/Strata (MIT licensed), with the data source swapped to a local NInfer server. This project is not affiliated with Strata or with NInfer upstream.

```bash
# Frontend changes take effect on page refresh (app.py serves the static page fresh each time)
# After backend changes, restart app.py; syntax check:
python3 -m py_compile app.py
```

Real-machine verification is still open: run it on the NInfer host and confirm the model name, uptime, and instant speed moving with a real request before calling it fully verified.
