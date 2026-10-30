# Configuration Guide

This page walks you through installing and configuring the **dess-monitor** Home Assistant integration. It covers the initial setup, every option in the Configure flow, the virtual-battery feature, recommended profiles, and migration notes.

---

## Table of contents

1. [Install / update](#1-install--update)
2. [Initial setup (login & device selection)](#2-initial-setup-login--device-selection)
3. [Options flow (Configure → reopen anytime)](#3-options-flow-configure--reopen-anytime)
4. [Virtual battery — per-device tuning](#4-virtual-battery--per-device-tuning)
5. [Recommended profiles](#5-recommended-profiles)
6. [Migrating from v0.3.x](#6-migrating-from-v03x)
7. [Troubleshooting](#7-troubleshooting)
8. [Want true local polling? — sister integration](#8-want-true-local-polling--sister-integration)

---

## 1. Install / update

1. Update the integration via **HACS** (or copy `custom_components/dess_monitor/` into your Home Assistant `custom_components/` directory).
2. **Restart Home Assistant.**
3. **Settings → Devices & Services → Add Integration → "Dess Monitor"** for a fresh install.
4. Existing installs keep their entry — open it and use **Configure** to access the new options.

---

## 2. Initial setup (login & device selection)

On the first form you'll see these fields:

| Field | What it does |
|---|---|
| **Username / Password** | Your `dessmonitor.com` cloud credentials. The password is hashed (SHA-1) before being stored. |
| **dynamic_settings** | Exposes writable Number/Select entities for inverter settings (output priority, max charging current, voltage thresholds…). Leave off if you only need read-only sensors. |
| **raw_sensors** | Adds raw/diagnostic sensors alongside the canonical ones. Useful for debugging unmapped firmware or for advanced users. |
| **direct_request_protocol** | Enables the new local-protocol path (Axpert / PI18 / SMG2 Modbus) via the cloud HEX transport. Required for direct-control features and lower-latency reads. |

After credentials are validated, you'll be asked to pick which devices from your account to expose to Home Assistant.

---

## 3. Options flow (Configure → reopen anytime)

Open the entry's **Configure** button to access the full options panel.

| Option | Default | Recommended | What it does |
|---|---|---|---|
| `main_update_interval` (s) | `60` | `60–120` | Cloud poll cadence for live data. **Range: 30–900.** Lower values = more requests against the cloud rate limit. |
| `direct_update_interval` (s) | `10` | `10–30` | Polling for the local/direct protocol path. **Range: 5–600.** |
| `dynamic_settings_interval` (s) | `300` | `300–600` | How often writable settings (output priority, charge current…) are re-read. **Range: 60–3600.** Keep high — these rarely change. |
| `enable_websocket` | `off` | **on** *(paid accounts only)* | Subscribe to the cloud WebSocket for push updates. **Requires the paid "fast data" / accelerated-telemetry add-on on your dessmonitor.com account** — without it the server will not deliver live frames over WS, and the option will have no effect. **Affects only the power sensors (grid, PV, battery, load)** — other entities still update on the regular polling cadence. Not all devcodes emit useful frames — leave off if you see no improvement. |
| `battery_virtual_enabled` | `off` | on (if SoC missing) | Enables the virtual battery (Coulomb-counting SoC + power) for inverters that don't publish `battery_capacity` directly. Per-device sizing is configured on the new Number/Select entities (see [section 4](#4-virtual-battery--per-device-tuning)). |
| `enable_last_at_sensors` | `off` | off | Adds freshness diagnostic sensors (`Last Sample Time`, `WebSocket Last Frame At`). Turn on only when debugging cloud lag. |
| `dynamic_settings` / `raw_sensors` / `direct_request_protocol` | as set on install | — | Same meaning as on the initial form; can be toggled later. |

> **Note on the cloud rate limit.** During summer peak hours `dessmonitor.com` aggressively rate-limits per-action calls (`err=3` / `err=6000`). If you see those in the logs, increase `main_update_interval` and/or `dynamic_settings_interval`.

---

## 4. Virtual battery — per-device tuning

After enabling `battery_virtual_enabled`, each selected device exposes new **CONFIG-category** entities:

| Entity | Purpose |
|---|---|
| **Number: Battery Capacity (Ah)** | Bank capacity. **Required** for SoC math — set to a value greater than 0. |
| **Number: Battery Voltage Full (V)** | Fully-charged terminal voltage of your bank (used to detect end-of-charge and rebase SoC to 100 %). |
| **Select: Battery Chemistry** | `lifepo4` (default), `lead_acid`, `li_ion`, `generic`. Affects rebase behavior near full. |

### How the SoC estimator works

The estimator integrates current over time (Coulomb counting) and **rebases SoC to 100 %** when:

- The absolute charging current drops below ~**2 % of capacity** (the conventional end-of-charge tail), **AND**
- Battery voltage is within ~**0.5 % of `Voltage Full`**.

If your reported SoC drifts:
1. Double-check **Capacity (Ah)** matches your actual bank.
2. Verify **Voltage Full** is correct for your chemistry and pack configuration.
3. For lead-acid, prefer rest voltage when available.

---

## 5. Recommended profiles

### Cloud-only, low request volume (avoid summer rate limits)

```yaml
main_update_interval: 120
dynamic_settings_interval: 600
enable_websocket: on   # only if you have the paid "fast data" add-on
```

### Real-time dashboards / energy tracking

```yaml
enable_websocket: on   # paid add-on required for power sensors
main_update_interval: 60
direct_request_protocol: on   # if your devcode supports it
```

### Inverter without battery SoC reporting (some Axpert / PI18 firmwares)

```yaml
battery_virtual_enabled: on
# then on each device:
#   Number: Battery Capacity (Ah) → e.g. 200
#   Number: Battery Voltage Full (V) → e.g. 56.8
#   Select: Battery Chemistry → lifepo4
```

---

## 6. Migrating from v0.3.x

- **No breaking config changes** — existing entries keep working.
- **New options default to `off`**, so behavior is unchanged until you opt in.
- After updating, open **Configure** once to review the new options and pick up `enable_websocket` if you want push updates (requires the paid add-on).
- If you previously relied on the legacy `api/commands/direct_commands.py` direct path, switch to **`direct_request_protocol = on`**; the implementation now goes through `api/protocols/` + `api/transports/`.

---

## 7. Troubleshooting

### Logs are full of `err=3` or `err=6000`

You're hitting the cloud's per-action rate limit. Increase `main_update_interval` (try `120–180`) and/or `dynamic_settings_interval` (try `600–1800`).

### `enable_websocket` is on but power sensors still lag

- Confirm your `dessmonitor.com` account actually has the **paid "fast data" / accelerated-telemetry** add-on. Without it the server won't push WS frames.
- Some `devcode`s simply don't publish useful frames — turn the option off if you see no improvement.
- Enable `enable_last_at_sensors` and watch **WebSocket Last Frame At** — if it doesn't update, no frames are arriving.

### Virtual battery SoC is wrong / drifts

- Capacity (Ah) and Voltage Full must match your real bank — recheck both.
- The estimator only rebases to 100 % when current is small **and** voltage is near `Voltage Full`. If your bank never reaches that voltage, SoC will keep drifting downward.
- Try switching **Chemistry** to better match your pack.

### Direct protocol entities missing

- Make sure `direct_request_protocol` is enabled in the options.
- Not every devcode is supported. Check the logs for "no protocol matched" warnings.

### Settings (Number / Select) don't change anything

- `dynamic_settings` must be enabled.
- The cloud takes a few seconds to acknowledge writes; entities re-read on `dynamic_settings_interval`.
- If a write times out (`DYNAMIC_SETTINGS_API_TIMEOUT = 5 s`), check the cloud's status and try again.

---

## Reporting issues

For bug reports and feature requests, please open an issue on GitHub.

> **Strongly recommended: attach a diagnostics file.**
> Without diagnostics most issues take several round-trips of "what does X say?" before anything actionable can be done. Attaching the file up front usually shortens that to a single reply.
>
> **How to grab it (built-in Home Assistant feature):**
> 1. **Settings → Devices & Services → Dess Monitor.**
> 2. Click your device (or the integration entry).
> 3. On the device page, open the three-dot menu (⋮) in the top-right of the **Device info** card and choose **Download diagnostics**.
> 4. A `.json` file will be saved to your computer. Drag-and-drop it into the GitHub issue.
>
> The file is automatically redacted by Home Assistant (credentials, tokens, etc. are stripped) — but glance through it before posting if you want to be extra sure nothing sensitive remains.
>
> Please also include:
> - Integration version (e.g. `v0.4.1.5`)
> - Home Assistant version
> - Inverter model + `devcode` (visible on the device page)
> - Whether `enable_websocket` / `direct_request_protocol` / `battery_virtual_enabled` are on
> - Relevant log lines (enable debug logging via `logger:` → `custom_components.dess_monitor: debug` if needed)

---

## 8. Want true local polling? — sister integration

This integration talks to your inverter **through the dessmonitor.com cloud** (REST + WebSocket). That works without extra hardware, but it depends on the cloud being reachable and on its rate limits.

If you want to bypass the cloud entirely and poll the inverter **directly over the local network / serial link**, check out the companion project:

### 👉 [home-assistant-dess-monitor-local](https://github.com/Antoxa1081/home-assistant-dess-monitor-local)

A standalone Home Assistant integration that speaks the native inverter protocols (Axpert / PI18 / SMG2 Modbus / …) **locally**, with no dessmonitor.com account required.

**Why you might want it:**

- ⚡ **Lower latency** — sub-second updates instead of cloud polling cadence.
- 🔒 **Fully offline** — works without internet, immune to cloud outages and rate limits (`err=3` / `err=6000` simply can't happen).
- 💰 **No paid add-on needed** — push-style updates without `dessmonitor.com`'s "fast data" subscription.
- 🔐 **Privacy** — your telemetry never leaves your LAN.
- 🧰 **Same protocol stack** — shares the parsing / CRC / status-bit primitives with this integration, so canonical sensors line up.

**What you need:** a wired connection to the inverter's RS-232 / RS-485 port (USB-serial adapter, ESP32 over TCP, or any setup that exposes the port to Home Assistant).

> **Both integrations can coexist** — many users keep this cloud integration for remote access / mobile dashboards while running the local one for fast in-house automations. Just make sure to give the entities distinct device names if you do.

For installation, supported devices, and wiring guides see the project's README:
**https://github.com/Antoxa1081/home-assistant-dess-monitor-local**
