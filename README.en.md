# NInfer Live Panel

[中文](./README.md) | English

A read-only live panel for an already-running NInfer server. It deploys, downloads, and starts no inference framework.

- **GET only, no POST**: it polls `/health`, `/v1/load`, `/stats`, `/metrics`, and `/slots`. No chat, no generation, no model load/unload, no NInfer configuration changes. If NInfer is offline, the panel just shows offline; it never starts NInfer for you.
- **Image**: `ghcr.io/izerok/ninfer-live-panel:latest` (built and pushed by GitHub Actions on every push to main).

## Quick start

```bash
docker compose up -d
```

Open http://127.0.0.1:8091/ . The panel is published to the host loopback only by default; do not change it to `0.0.0.0` for public exposure (see [Security](#security)).

Without compose:

```bash
docker run -d --name ninfer-panel -p 127.0.0.1:8091:8091 \
  -v ninfer-panel-data:/app/data \
  ghcr.io/izerok/ninfer-live-panel:latest
```

From source (Python 3.12, no third-party dependencies):

```bash
python3 app.py
```

## What is on screen

| Section | Content |
| --- | --- |
| Model state | Five states: idle / reading / generating / queued / error. NInfer has no single state field; this is the panel's documented mapping from running / waiting / prefilling / decode_ready, not a server field. |
| 8 metric cards | Decode and prefill speed, GPU load, VRAM, GPU temperature, power, PCIe link, CPU, disk read. Each card has a 60-second sparkline (page-local; it is lost on refresh — see History below). |
| History | Decode and prefill speed curves, switchable between 15 minutes / 1 hour / 24 hours, with hover values. |
| Current requests | In-flight slots, one row each: slot id, prompt length, cached portion, context window, share of window. |
| Context usage | Window limit (`capacity.max_context` from `/v1/load`), KV cache usage, system memory, GPU temperature. |
| Conversation cache | Retained slot count and host KV, plus cumulative reused tokens. |

## Settings: edit the NInfer address in the UI

The compose file does **not** hardcode a NInfer address. Use the Settings card at the top of the panel (for example `http://host.docker.internal:8080`, or `http://ninfer-unc:8080` when NInfer is another container on the same network). Saving takes effect immediately — no compose edit, no panel restart.

Precedence: **UI-saved address > `NINFER_BASE_URL` environment variable > image default**. The saved value lives in `settings.json` in the data volume and survives refreshes, restarts, and recreates. Without the data volume, the file lives in the container layer: refresh- and restart-safe, but lost on recreate.

## Why the history survives a refresh

The old sparklines lived only in browser memory, so a refresh wiped them. The history curve is now sampled by the backend every 2 seconds and written to `history.jsonl` in the data volume: it survives page refreshes, container restarts, and recreates (as long as the data volume is mounted), and resumes from disk after a panel restart. Only the last 24 hours are kept; older points are pruned automatically.

The curve contains only aggregate rates (decode / prefill tok/s, KV usage, GPU load) — no prompt or generated text.

## Dark / light and languages

- The button in the top right switches dark / light. Before the user chooses, it follows the system; once chosen, the choice is stored in browser `localStorage`.
- The language selector in the top right switches 中文 / English, also stored in `localStorage`. Before a choice, the browser language decides (Chinese → Chinese, anything else → English). All UI strings come from one dictionary in the frontend; no external language pack is loaded.
- To add a language: add a section to the `I18N` dictionary in `web/index.html` and an option to the language selector. Missing keys fall back to Chinese.

## Data sources and definitions

| Endpoint | Used for |
| --- | --- |
| `/health` | Online or not, version |
| `/v1/load` | Model, uptime, capacity, admitted / running / waiting / prefilling / decode_ready, KV usage, cumulative prefill / decode counts |
| `/stats` | Cumulative averages, queue depth, peak admitted |
| `/metrics` | Requests completed / failed / rejected, KV usage ratio, draft accept rate, cumulative average speeds |
| `/slots` | Slot totals, in-flight and retained counts; in-flight slots' prompt lengths and cached portions |
| `nvidia-smi` | GPU load, VRAM, temperature, power (needs the NVIDIA container toolkit and GPU passthrough on the host; otherwise the cards say unavailable) |
| Host `/proc` (read-only mount) | System memory, CPU, disk throughput (without the mount these say unavailable; the container's own numbers are never substituted) |

Two speeds, kept apart:

- **Instant speed**: the backend samples cumulative counters every 2 seconds and computes (this − last) / interval. The page labels it as such.
- **15-minute average**: the backend keeps counter samples for 900 seconds and computes the window average; before 15 minutes have passed, the card shows the actual window length instead of pretending it is a 15-minute average.
- **Cumulative average**: the since-startup average from NInfer's own `/metrics` / `/stats`, shown separately.

## What is deliberately not invented

Fields that exist in Strata but not in NInfer are never fabricated:

- **Per-request progress**: `/slots` does not report it, so the progress bar only animates while reading / generating; it never shows a fake percentage.
- **Request history**: NInfer has no history API, so there is no “recent requests” table; the “current requests” table lists only slots in flight right now. Queued requests are a count only, with no per-request detail.
- **Experts in VRAM**: a Strata MoE cache concept that NInfer does not have; the context section uses NInfer's KV cache instead.
- **PCIe transfer rate**: not reported by NInfer, and a single `nvidia-smi` query only gives the link generation / width, so the PCIe card shows the link and says the rate is not reported.
- **Generated token counts**: `/slots` has none, so the current-requests table shows prompt length only, not output tokens.
- **Unreachable fields**: shown as “unavailable”, never as 0 (0 would be misread as a measured value).

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `NINFER_BASE_URL` | `http://host.docker.internal:8080` | NInfer address on first run; ignored once an address is saved in the UI |
| `NINFER_API_KEY` | empty | Only if NInfer was started with an API key; the backend sends it as a Bearer token to read endpoints and never puts it in a snapshot or the frontend |
| `PANEL_BIND` / `PANEL_PORT` | `0.0.0.0` / `8091` | In-container listen address and port; public exposure is controlled by compose's `127.0.0.1:8091:8091` mapping |
| `POLL_INTERVAL` | `2` | Backend poll interval in seconds |
| `PANEL_HISTORY_FILE` | `/app/data/history.jsonl` | History curve file |
| `PANEL_SETTINGS_FILE` | `/app/data/settings.json` | UI-saved address file |
| `PANEL_UPDATE_CHECK` | `1` | Set to `0` to disable the upgrade check (offline hosts) |
| `VERSION` (file, not an env var) | repo root | Current version; image and Release tags both come from it |

## Version, upgrade check, and release flow

- **Version**: the `VERSION` file at the repo root is the current version (for example `0.1.0`). The panel shows it in the header, and the image is tagged both `:latest` and `:v0.1.0`.
- **Upgrade check**: once an hour (cached for 1 hour) the panel asks the public GitHub Releases API for this repository's latest release. It reads a public record only — no token, no panel data, no telemetry. If the check fails or no release exists yet, the banner simply stays hidden. When a newer release exists, a banner appears at the top with a link to the Release. Fully offline hosts can set `PANEL_UPDATE_CHECK=0` to disable it.
- **Change flow**: `main` is protected; nothing is pushed to it directly. Changes go through a normal PR: branch → push branch → open PR → at least 1 approval + the `build-and-push` check passing → merge. After merging to main, Docker Publish builds and pushes the image, and on a successful build the Release workflow creates a Release automatically (skipped when `VERSION` did not change, so no duplicate releases).

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

## Layout source

The layout replicates the `apps/host` Monitor screen of Niko1221/Strata (MIT licensed), with the data source swapped to a local NInfer server. This project is not affiliated with Strata or with NInfer upstream.

## Development

```bash
# Frontend changes take effect on page refresh (app.py serves the static page fresh each time)
# After backend changes, restart app.py; syntax check:
python3 -m py_compile app.py
```

Real-machine verification is still open: run it on the NInfer host and confirm the model name, uptime, and instant speed moving with a real request before calling it fully verified.
