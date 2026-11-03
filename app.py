#!/usr/bin/env python3
"""NInfer live panel backend — read-only, stdlib only.

What it does, and nothing else:
  * every poll it GETs the local NInfer server's own read endpoints:
    /health, /v1/load, /stats, /metrics (and /slots for the processing count)
  * it computes *instant* decode / prefill rates from counter deltas
    (committed_decode_tokens / computed_prefill_tokens between two polls).
    NInfer's own /metrics and /stats only give cumulative averages, so a
    "right now" tok/s has to come from a delta — that is the one number
    this panel derives, and it says so in the UI.
  * it optionally runs `nvidia-smi` (host-injected by the NVIDIA container
    toolkit) for GPU utilisation / memory / temperature / power.
  * it optionally reads /host/proc/meminfo (host /proc mounted read-only)
    for host system memory. Without that mount it reports system memory
    as unavailable — it never substitutes the container's own meminfo,
    which would be the wrong machine's numbers.

What it never does:
  * no POST to NInfer (no load/unload/chat/generation), no model download,
    no engine start, no Strata anything. If NInfer is down, the panel
    says offline; it does not start anything to fill the gap.

State mapping (the panel's own mapping — NInfer exposes no single
"state" field, so this is documented, not quoted from the server):
  offline  : /health unreachable or not ok
  queued   : waiting > 0 and running == 0
  warming  : prefilling > 0 and decode_ready == 0
  generating: decode_ready > 0, or running > 0
  idle     : otherwise (loaded, nothing running or waiting)

Environment:
  NINFER_BASE_URL  default http://host.docker.internal:8080
                   (set to http://ninfer-unc:8080 if both containers share
                   a user network, or http://127.0.0.1:8080 with host networking)
  NINFER_API_KEY   optional; sent as Bearer on the read endpoints that
                   require it. /health itself is public in NInfer.
  PANEL_BIND / PANEL_PORT  default 0.0.0.0:8091 (compose publishes it
                   as 127.0.0.1:8091 on the host — see docker-compose.yml)
  POLL_INTERVAL    seconds between backend refreshes, default 2
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get("NINFER_BASE_URL", "http://host.docker.internal:8080").rstrip("/")
API_KEY = os.environ.get("NINFER_API_KEY", "")
BIND = os.environ.get("PANEL_BIND", "0.0.0.0")
PORT = int(os.environ.get("PANEL_PORT", "8091"))
POLL = float(os.environ.get("POLL_INTERVAL", "2"))
WEB_DIR = Path(__file__).resolve().parent / "web"

_lock = threading.Lock()
_snapshot = {"ninfer_ok": False, "state": "offline", "error": "not polled yet"}
_prev = None  # (timestamp, decode_tokens, prefill_tokens)
# Rolling 15-minute window: counter samples kept for 900 s so the panel
# can show a true "last 15 minutes" average like the screenshot panel,
# not just the since-startup average NInfer itself reports.
from collections import deque as _deque
_history = _deque()  # (timestamp, decode_tokens, prefill_tokens)
_prev_cpu = None  # (timestamp, total_jiffies, idle_jiffies)


def _get(path, timeout=3):
    req = urllib.request.Request(BASE + path)
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)
    req.add_header("Accept", "application/json, text/plain")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _num(obj, *keys, default=0):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    try:
        return float(cur)
    except (TypeError, ValueError):
        return default


def _parse_metrics(text):
    """Parse the few Prometheus series the panel shows. Unknown / missing
    series stay absent (None) instead of being invented as zero."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        name, _, value = line.partition(" ")
        base = name.split("{")[0]
        try:
            out[base] = float(value)
        except ValueError:
            pass
    return out


def _gpu():
    """nvidia-smi if the toolkit injected it, else an explicit unavailable."""
    try:
        proc = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,pcie.link.gen.current,pcie.link.width.current",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "nvidia-smi not found in this container"}
    if proc.returncode != 0:
        return {"available": False,
                "reason": (proc.stderr or proc.stdout).strip()[:200] or "nvidia-smi failed"}
    cards = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            card = {
                "name": parts[0],
                "util_percent": float(parts[1]),
                "mem_used_mb": float(parts[2]),
                "mem_total_mb": float(parts[3]),
                "temp_c": float(parts[4]),
                "power_w": float(parts[5]),
            }
            # power.limit / PCIe link may report "[N/A]" on some cards.
            for key, idx in (("power_limit_w", 6), ("pcie_gen", 7), ("pcie_width", 8)):
                if len(parts) > idx:
                    try:
                        card[key] = float(parts[idx])
                    except ValueError:
                        card[key] = None
            cards.append(card)
        except ValueError:
            continue
    if not cards:
        return {"available": False, "reason": "nvidia-smi returned no GPU rows"}
    return {"available": True, "cards": cards}


def _host_cpu():
    """Host CPU utilisation from /host/proc/stat deltas. Without the host
    /proc mount this is unavailable — the container's own numbers are not
    substituted, for the same reason as host memory."""
    global _prev_cpu
    path = Path("/host/proc/stat")
    if not path.is_file():
        return {"available": False,
                "reason": "host /proc not mounted (see README: /proc:/host/proc:ro)"}
    try:
        parts = path.read_text().splitlines()[0].split()[1:]
        vals = [int(x) for x in parts]
        total = sum(vals)
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    except Exception as exc:
        return {"available": False, "reason": f"could not parse /host/proc/stat: {exc}"}
    now = time.time()
    util = None
    if _prev_cpu is not None:
        prev_t, prev_total, prev_idle = _prev_cpu
        dt_total = total - prev_total
        dt_idle = idle - prev_idle
        if dt_total > 0:
            util = (1.0 - dt_idle / dt_total) * 100.0
    _prev_cpu = (now, total, idle)
    model = cores = None
    cpuinfo = Path("/host/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            text = cpuinfo.read_text()
            for line in text.splitlines():
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
            cores = text.count("processor\t:")
        except Exception:
            pass
    return {"available": True, "util_percent": util, "model": model, "cores": cores}


_prev_disk = None  # (timestamp, sectors_read, sectors_written)


def _host_disk():
    """Host disk throughput from /host/proc/diskstats deltas (whole disks
    only: sd/vd/nvme/mmcblk devices, not partitions, loop or ram devices).
    Without the host /proc mount this is unavailable."""
    global _prev_disk
    path = Path("/host/proc/diskstats")
    if not path.is_file():
        return {"available": False,
                "reason": "host /proc not mounted (see README: /proc:/host/proc:ro)"}
    import re as _re
    read_sectors = write_sectors = 0
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            if not _re.match(r"^(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$", name):
                continue
            read_sectors += int(parts[5])
            write_sectors += int(parts[9])
    except Exception as exc:
        return {"available": False, "reason": f"could not parse /host/proc/diskstats: {exc}"}
    now = time.time()
    read_mbs = write_mbs = None
    if _prev_disk is not None:
        prev_t, prev_r, prev_w = _prev_disk
        dt = now - prev_t
        if dt > 0 and read_sectors >= prev_r and write_sectors >= prev_w:
            read_mbs = (read_sectors - prev_r) * 512 / 1048576 / dt
            write_mbs = (write_sectors - prev_w) * 512 / 1048576 / dt
    _prev_disk = (now, read_sectors, write_sectors)
    return {"available": True, "read_mbs": read_mbs, "write_mbs": write_mbs}


def _host_mem():
    """Host memory only when host /proc is mounted at /host/proc.
    The container's own /proc/meminfo is deliberately never used."""
    path = Path("/host/proc/meminfo")
    if not path.is_file():
        return {"available": False,
                "reason": "host /proc not mounted (see README: /proc:/host/proc:ro)"}
    total = avail = None
    for line in path.read_text().splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])  # KiB
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
    if total is None:
        return {"available": False, "reason": "could not parse /host/proc/meminfo"}
    used = total - (avail or 0)
    return {"available": True, "total_mb": total / 1024.0, "used_mb": used / 1024.0,
            "used_percent": (used / total * 100.0) if total else None}


def _poll_once():
    global _prev
    now = time.time()
    snap = {"as_of": now, "ninfer_base_url": BASE, "ninfer_ok": False,
            "state": "offline", "error": None}
    try:
        status, health_body = _get("/health", timeout=3)
        health = json.loads(health_body) if health_body.strip().startswith("{") else {}
        snap["health"] = {"http": status, "status": health.get("status"),
                          "version": health.get("version")}
        if status != 200 or health.get("status") not in (None, "ok"):
            snap["error"] = f"/health -> HTTP {status} status={health.get('status')}"
            return snap
    except Exception as exc:  # unreachable, timeout, bad JSON: all mean offline
        snap["error"] = f"cannot reach {BASE}/health: {exc}"
        return snap

    try:
        _, load_body = _get("/v1/load", timeout=3)
        load = json.loads(load_body)
    except Exception as exc:
        snap["error"] = f"/health ok but /v1/load failed: {exc}"
        return snap

    snap["ninfer_ok"] = True
    req = load.get("requests", {}) or {}
    occ = load.get("occupancy", {}) or {}
    cap = load.get("capacity", {}) or {}
    ctr = load.get("counters", {}) or {}
    running = int(_num(req, "running"))
    waiting = int(_num(req, "waiting"))
    prefilling = int(_num(req, "prefilling"))
    decode_ready = int(_num(req, "decode_ready"))
    admitted = int(_num(req, "admitted"))
    decode_tokens = int(_num(ctr, "committed_decode_tokens"))
    prefill_tokens = int(_num(ctr, "computed_prefill_tokens"))
    kv_tokens = int(_num(occ, "device_main_kv_tokens"))
    kv_cap = int(_num(cap, "kv_capacity_tokens"))

    # Instant rates from counter deltas; a counter reset yields None, not a spike.
    decode_rate = prefill_rate = window = None
    if _prev is not None:
        prev_t, prev_d, prev_p = _prev
        dt = now - prev_t
        if dt > 0 and decode_tokens >= prev_d and prefill_tokens >= prev_p:
            decode_rate = (decode_tokens - prev_d) / dt
            prefill_rate = (prefill_tokens - prev_p) / dt
            window = dt
    _prev = (now, decode_tokens, prefill_tokens)
    _history.append((now, decode_tokens, prefill_tokens))
    while _history and now - _history[0][0] > 900:
        _history.popleft()
    rolling = {"decode_tok_s": None, "prefill_tok_s": None, "window_seconds": None}
    if len(_history) >= 2:
        t0, d0, p0 = _history[0]
        span = now - t0
        if span >= 30:
            rolling = {"decode_tok_s": (decode_tokens - d0) / span,
                       "prefill_tok_s": (prefill_tokens - p0) / span,
                       "window_seconds": span}

    if waiting > 0 and running == 0:
        state = "queued"
    elif prefilling > 0 and decode_ready == 0:
        state = "warming"
    elif decode_ready > 0 or running > 0:
        state = "generating"
    else:
        state = "idle"

    snap.update({
        "state": state,
        "model": load.get("model"),
        "uptime_seconds": _num(load, "uptime_seconds"),
        "requests": {"admitted": admitted, "running": running,
                     "waiting": waiting, "prefilling": prefilling,
                     "decode_ready": decode_ready,
                     "materializing": int(_num(req, "materializing"))},
        "kv": {"tokens": kv_tokens, "capacity_tokens": kv_cap,
               "used_percent": (kv_tokens / kv_cap * 100.0) if kv_cap else None},
        # Context window: the one thing the first version never showed.
        # max_context comes from /v1/load capacity (your ninfer-unc runs
        # with --max-context 262144). KV tokens are the device KV cache
        # occupancy — related to context, but not the same as a request's
        # prompt length, so the two are shown separately, never merged
        # into one invented "context used" number.
        "context": {
            "max_context": int(_num(cap, "max_context")),
            "max_concurrency": int(_num(cap, "max_concurrency")),
            "kv_tokens": kv_tokens,
            "kv_capacity_tokens": kv_cap,
            "kv_used_percent": (kv_tokens / kv_cap * 100.0) if kv_cap else None,
            "device_state_slots_used": int(_num(occ, "device_state_slots")),
            "device_state_slots_capacity": int(_num(cap, "device_state_slots")),
            "host_state_slots_used": int(_num(occ, "host_state_slots")),
            "host_state_slots_capacity": int(_num(cap, "host_state_slots")),
            "host_kv_bytes": int(_num(occ, "host_kv_bytes")),
            "host_kv_capacity_bytes": int(_num(cap, "host_kv_bytes")),
        },
        "counters": {"decode_tokens": decode_tokens,
                     "prefill_tokens": prefill_tokens,
                     "reused_prompt_tokens": int(_num(ctr, "reused_prompt_tokens")),
                     "decode_rounds": int(_num(ctr, "decode_rounds"))},
        "instant": {"decode_tok_s": decode_rate, "prefill_tok_s": prefill_rate,
                    "window_seconds": window},
        "rolling": rolling,
    })
    # Cumulative averages from /stats, best effort — absent is absent.
    try:
        _, stats_body = _get("/stats", timeout=3)
        stats = json.loads(stats_body)
        tps = stats.get("throughput_tokens_per_second") or {}
        snap["cumulative_avg"] = {
            "decode_tok_s": tps.get("decode") if isinstance(tps, dict) else None,
            "prefill_tok_s": tps.get("prefill") if isinstance(tps, dict) else None,
            "peak_admitted": stats.get("requests", {}).get("peak_admitted"),
            "queue_depth": stats.get("queue", {}).get("depth"),
        }
        # /stats throughput block shape varies by build; keep raw keys the UI may use.
        snap["cumulative_avg"]["raw_throughput_block"] = tps
    except Exception:
        snap["cumulative_avg"] = None
    try:
        _, metrics_body = _get("/metrics", timeout=3)
        m = _parse_metrics(metrics_body)
        draft_total = m.get("ninfer:draft_tokens_total")
        draft_acc = m.get("ninfer:draft_accepted_tokens_total")
        snap["metrics"] = {
            "requests_total": m.get("ninfer:requests_total"),
            "requests_failed_total": m.get("ninfer:requests_failed_total"),
            "requests_rejected_total": m.get("ninfer:requests_rejected_total"),
            "kv_cache_usage_ratio": m.get("llamacpp:kv_cache_usage_ratio"),
            "draft_accept_rate": (draft_acc / draft_total) if draft_total else None,
            "avg_decode_tok_s": m.get("llamacpp:predicted_tokens_seconds"),
            "avg_prefill_tok_s": m.get("llamacpp:prompt_tokens_seconds"),
        }
    except Exception:
        snap["metrics"] = None
    try:
        _, slots_body = _get("/slots", timeout=3)
        slots = json.loads(slots_body)
        if isinstance(slots, list):
            processing = [s for s in slots if s.get("is_processing")]
            # Per-request context length as NInfer reports it: prompt tokens
            # (cached tokens are the reused prefix part of that prompt).
            # Generated tokens so far are not in /slots, so this is prompt
            # length only — the UI labels it as such.
            details = [{"id": s.get("id"),
                        "prompt_tokens": int(s.get("n_prompt_tokens") or 0),
                        "cached_tokens": int(s.get("n_prompt_tokens_cache") or 0),
                        "n_ctx": int(s.get("n_ctx") or 0)}
                       for s in processing]
            snap["slots"] = {"total": len(slots),
                             "processing": len(processing),
                             "retained": sum(1 for s in slots if s.get("retained")),
                             "processing_details": details,
                             "processing_prompt_tokens": sum(d["prompt_tokens"] for d in details),
                             "max_processing_prompt_tokens": max(
                                 (d["prompt_tokens"] for d in details), default=0)}
            ctx = snap.get("context") or {}
            max_ctx = ctx.get("max_context") or 0
            ctx["max_processing_prompt_tokens"] = snap["slots"]["max_processing_prompt_tokens"]
            ctx["processing_prompt_tokens"] = snap["slots"]["processing_prompt_tokens"]
            ctx["max_prompt_share_percent"] = (
                snap["slots"]["max_processing_prompt_tokens"] / max_ctx * 100.0
                if max_ctx else None)
            snap["context"] = ctx
    except Exception:
        pass
    snap["gpu"] = _gpu()
    snap["host_memory"] = _host_mem()
    snap["host_cpu"] = _host_cpu()
    snap["host_disk"] = _host_disk()
    return snap


def _poller():
    while True:
        try:
            snap = _poll_once()
        except Exception as exc:  # never kill the poller on a bad sample
            snap = {"ninfer_ok": False, "state": "offline", "error": str(exc),
                    "as_of": time.time(), "ninfer_base_url": BASE}
        with _lock:
            _snapshot.clear()
            _snapshot.update(snap)
        time.sleep(POLL)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/api/health", "/api/snapshot"):
            with _lock:
                body = json.dumps(_snapshot)
            self._send(200, body, "application/json")
            return
        if self.path in ("/", "/index.html"):
            self._send(200, (WEB_DIR / "index.html").read_text(), "text/html; charset=utf-8")
            return
        self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    threading.Thread(target=_poller, daemon=True).start()
    print(f"ninfer-live-panel: polling {BASE} every {POLL}s, listening on {BIND}:{PORT}",
          flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
