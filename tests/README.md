# Tests

Unit/integration test-suite for the `dess_monitor` integration. ~1000 tests,
~96% line coverage. Follows the same two-mode convention as the sibling
`dess-monitor-local` repo.

## Two modes (chosen automatically by `tests/conftest.py`)

* **HA absent** — pure-logic tests only. `conftest.py` stubs the top-level
  package so the HA-importing `__init__.py` never runs; the HA-free modules
  (`sdk`, `api`, `mapping`, …) import standalone. HA-dependent test files
  self-skip via `pytest.importorskip(...)`. Needs only
  `pytest pytest-cov pytest-asyncio aiohttp`.
* **HA present** — the full suite (pure + the HA integration layer). Provides
  the `hass` fixture from `pytest-homeassistant-custom-component`. On Windows,
  `conftest.py` works around the harness's socket / event-loop guards.

## Install & run

```bash
# pure-logic only (no Home Assistant)
pip install pytest pytest-cov pytest-asyncio aiohttp
pytest                       # HA tests skip with a reason

# full suite (pulls a pinned Home Assistant; POSIX-friendly)
pip install -c <(echo "homeassistant==2025.3.0") -r requirements-test.txt
pytest --cov --cov-report=term-missing
```

Config lives in `pytest.ini` (collection + asyncio) and `pyproject.toml`
(`[tool.ruff]` lint + `[tool.coverage]`, branch coverage).

On **Windows** the HA harness prints harmless `Exception ignored in __del__ ...
ProactorEventLoop ... _ssock` teardown noise. Filter it:

```bash
pytest 2>&1 | grep -vE "_ssock|proactor_events|base_events|__del__|Exception ignored|self.close|_close_self_pipe"
```

## Lint

```bash
ruff check custom_components/dess_monitor tests
```

## CI (`.github/workflows/tests.yml`)

Three jobs: **lint** (ruff), **pytest** (matrix 3.12/3.13, pure-logic, no HA),
**hass** (Linux, full suite with a pinned HA). `hacs.yaml` / `hassfest.yaml`
cover HACS + manifest validation.

## Layout

- `conftest.py` — dual-mode bootstrap + Windows workarounds + shared fixtures.
- `test_sdk_*`, `test_protocols_*`, `test_parsing|enums|helpers|util|mapping_*`,
  `test_transports`, `test_streaming` — pure-logic, run in every mode.
- HA-dependent (guarded, run only with HA): `test_virtual_battery`,
  `test_device_cache`, `test_stores`, `test_data_resolvers`, `test_config_flow`,
  `test_diagnostics`, `test_hub`, `test_coordinator_*`, `test_sensor_platform`,
  `test_sensors_entities`, `test_select_number`, `test_entities_extra`,
  `test_init_setup`, `test_stream_manager`.
- `test_protocols_smoke.py` — legacy standalone runner (module-level asserts +
  `sys.exit`); excluded from collection via `collect_ignore`. Run directly with
  `python tests/test_protocols_smoke.py`.
