# DESS Monitor — Home Assistant integration

Cloud-backed integration for inverters / hybrid solar systems sold under the
**SmartESS**, **EnergyMate**, **Fronus Solar** mobile apps, and the
[**dessmonitor.com**](https://www.dessmonitor.com) /
[**eybond.com**](https://www.eybond.com) web monitor.

It talks to the cloud over REST + WebSocket and exposes:

- **Canonical sensors** — battery / grid / PV / load / energy totals, normalized across firmwares.
- **Direct-protocol sensors** — Axpert (PI30), InfiniSolar PI18, and SMG2 Modbus RTU, relayed through the cloud's HEX transport.
- **Writable settings** — output priority, max charging current, voltage thresholds, etc. (Number / Select entities).
- **Virtual battery** — Coulomb-counting SoC for inverters that don't publish capacity directly.
- **Optional WebSocket push** — sub-cadence updates for power sensors when the account has the paid "fast data" add-on.

---

## 📚 Documentation

- **[Wiki](https://github.com/Antoxa1081/home-assistant-dess-monitor/wiki)** — supported devices, FAQ, troubleshooting, recipes.
- **[Configuration guide](docs/Configuration.md)** — every option in the config / options flow, recommended profiles, virtual-battery tuning, migration notes.

---

## Installation via HACS (recommended)

🎉 The repository is in the HACS default community store.

Search for **DESS Monitor** in HACS and install it directly.

If it isn't listed, add the repo manually:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Antoxa1081&repository=home-assistant-dess-monitor&category=Integration)

Or for HACS 2.0+:

1. Open the [HACS](https://hacs.xyz) panel.
2. Three-dot menu → **Custom Repositories**.
3. Add:
   - **URL:** `https://github.com/Antoxa1081/home-assistant-dess-monitor`
   - **Type:** Integration
4. Click **Add**, then install **DESS Monitor** from the store.
5. Restart Home Assistant.

Then **Settings → Devices & Services → Add Integration → DESS Monitor**.

> **Minimum Home Assistant version: 2024.11**

---

## Features at a glance

| Area | What you get |
|---|---|
| **Cloud REST polling** | Live data + energy flow + parameter catalog (`queryDeviceParsEs`) on configurable cadence. |
| **WebSocket push** | Optional push updates for power sensors (paid "fast data" account add-on required). |
| **Direct protocols** | `axpert` (PI30 ASCII) · `pi18` (InfiniSolar) · `smg2_modbus` (RTU). Selectable per entry. |
| **Dynamic settings** | Writable Number / Select entities for inverter configuration values. |
| **Virtual battery** | Per-device capacity (Ah), full voltage, chemistry → SoC + power sensors. |
| **Diagnostics** | Built-in HA diagnostics download (auto-redacted). Optional freshness sensors (`Last Sample Time`, `WebSocket Last Frame At`). |

See the [Configuration guide](https://github.com/Antoxa1081/home-assistant-dess-monitor/wiki) for every option and recommended profile.

---

## Tested devcodes

`2341`, `2376`, `2428` and others reported by the community — see the [Wiki](https://github.com/Antoxa1081/home-assistant-dess-monitor/wiki) for the up-to-date list.

If your inverter isn't recognized or a value looks wrong, **please open an issue with a diagnostics file attached** (Settings → Devices & Services → Dess Monitor → ⋮ → *Download diagnostics*). Include the inverter model and `devcode` (visible on the device page).

---

## Want true local polling? — sister integration

This integration goes **through the dessmonitor.com cloud**. If you want to bypass the cloud and poll the inverter **directly over the local network / serial link**:

### 👉 [home-assistant-dess-monitor-local](https://github.com/Antoxa1081/home-assistant-dess-monitor-local)

Speaks the native protocols (Axpert / PI18 / SMG2 Modbus) **locally** — no account, no rate limits, sub-second updates. Both integrations can coexist.

---

## Related projects

- **[dess-monitor-mqtt](https://github.com/Antoxa1081/dess-monitor-mqtt)** — standalone MQTT client for NodeRED / non-HA setups.

---

<img src="https://github.com/user-attachments/assets/9e35a387-8049-414a-b0f6-b55dc914e489" width="60%"/>
<img src="https://github.com/user-attachments/assets/b3d86bd4-2e7f-4d81-9d47-2ce4719f1bdd" width="40%"/>
<img src="https://github.com/user-attachments/assets/07b09a9a-f7b3-4715-82ec-f8a2ccffe70e" width="20%"/>
<img src="https://github.com/user-attachments/assets/51cd2196-7d98-4218-8e0c-49ca13c3c1cc" width="20%"/>

## License

[MIT](LICENSE)
