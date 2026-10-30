# Canonical sensor source refactor — plan

**Status**: not started. Captured 2026-04-26 to defer until after PI18 was wired
into the config flow.

## Goal

Replace the current dual-coordinator + `Direct*` sensor split with a single,
**user-chosen primary source per config entry**:

- `CLOUD_API` — REST/WS endpoints on `dessmonitor.com` (today's `MainCoordinator`).
- `LOCAL_AXPERT` — cloud-relay + Voltronic PI30 ASCII frames (current direct path).
- `LOCAL_SMG2` — cloud-relay + Modbus RTU.
- `LOCAL_PI18` — cloud-relay + InfiniSolar-V PI18 frames.

(`LOCAL_*` is misleading — transport is still cloud — but the wire-level
dialect is the inverter's native one. Naming is the user's call.)

`Direct*` sensors get removed. Only canonical sensors remain.

## Architectural decision: hybrid (canonical core + per-protocol extras)

Not pure-canonical (loses protocol-specific signal) and not fully dynamic per
protocol (entity_ids would change when the user switches sources, breaking
their automations).

- **Canonical core** — stable set of sensors (`battery_voltage`, `grid_voltage`,
  `output_active_power`, `load_percent`, `pv_charging_power`,
  `inverter_temperature`, `operating_mode`, `output_priority`, `battery_type`,
  …). Same entity_ids regardless of source.
- **Per-protocol extras** — each protocol declares optional sensors that only
  appear when that protocol is selected (e.g. PI18: `mppt1/2_temp`,
  `mppt_status`, `parallel_id`; Axpert: QPIWS warnings, QBEQI equalization).

## Coverage matrix (sketch)

| Canonical              | CLOUD_API | AXPERT | SMG2 | PI18 |
|------------------------|-----------|--------|------|------|
| `battery_voltage`      | last_data | QPIGS  | r215 | GS   |
| `grid_voltage`         | ✓         | QPIGS  | r202 | GS   |
| `output_priority`      | pars      | QPIRI  | r301 | PIRI |
| `pv_charging_power`    | ✓         | QPIGS  | calc | GS   |
| `operating_mode`       | ✓         | QMOD   | r201 | MOD  |
| `energy_total_kwh`     | ✓         | ✗      | ?    | ET   |
| `mppt2_temp` (extra)   | ✗         | ✗      | ✗    | GS   |
| `parallel_id` (extra)  | ✗         | ✗      | ✗    | GS   |

**Energy totals policy** — Axpert has no protocol-level totals. Two policies:
- *Strict*: AXPERT-only entry has no energy totals.
- *Pragmatic*: a side cloud poll fetches energy totals regardless of selected
  protocol. Recommended.

## Layout

```
sensors/
├── canonical.py            # registry: name, unit, device_class, candidates
├── extras/
│   ├── axpert.py           # QPIWS warnings, QBEQI equalization
│   ├── pi18.py             # MPPT temps, parallel id, fault code, PV2 *
│   └── smg2_modbus.py      # configuration registers as Number/Select
api/protocols/
├── axpert/
│   ├── protocol.py
│   ├── set_commands.py
│   └── candidates.py       # canonical_name → ("qpigs", "battery_voltage")
├── pi18/
│   ├── protocol.py
│   └── candidates.py
└── smg2_modbus/
    ├── protocol.py
    └── candidates.py
mapping/
├── seed.py                 # cloud provider candidates (as today)
└── candidates.py           # merge cloud-seed + protocol candidates by name
coordinators/
├── coordinator.py          # MainCoordinator → cloud (always for energy under pragmatic)
└── direct_coordinator.py   # DirectCoordinator → selected protocol
```

`canonical.py` is the single source of truth for the canonical sensor set.
Each entry carries a `candidates` list — every possible source for the value
(`CloudCandidate(provider_key, scale)` or
`ProtocolCandidate(protocol, section, key)`). At sensor-create time the
resolver picks the first candidate matching the active source.

## Setup flow

1. User picks source at install (`CONF_PROTOCOL` or current `CONF_DIRECT_PROTOCOL`).
2. Integration spins up the right coordinator:
   - `CLOUD_API` → `MainCoordinator` only.
   - `LOCAL_*` → `DirectCoordinator` with that protocol's binding (+ side cloud
     poll for energy totals if pragmatic policy).
3. Sensor platform creates:
   - Canonical sensors that have a candidate matching the active source.
   - Extras declared by the active protocol's `extras/<protocol>.py`.

## Step-by-step

1. Trash `Direct*` sensor classes; sketch `sensors/canonical.py`.
2. Extend `seed.py` candidate types — accept `ProtocolCandidate(protocol,
   section, key)` next to `ProviderKeyCandidate`. Resolver filters by active
   source.
3. Add `candidates.py` (or inline in protocol package `__init__`) to each
   protocol mapping canonical → section/key.
4. Patch `MappingDiscovery` to honour the active source when picking the
   candidate.
5. `__init__.py` integration setup reads `CONF_PROTOCOL` and decides which
   coordinators to start.
6. `sensor.py` platform creates canonical + protocol-specific extras.
7. Delete `direct_sensor.py` / `Direct*` classes. Migrate any unique features
   (output_priority, battery_type) into canonical or extras.
8. Tests: extend smoke so every protocol has a candidate covering each
   canonical it claims to support (per the matrix).

Steps 1–2 are the foundation; 3–6 follow naturally; 7–8 finish off.
