"""Test bootstrap for the dess_monitor integration.

Two modes, chosen automatically by whether Home Assistant is importable:

* **HA present** (local dev box, the Linux CI "hass" job): the real package
  ``__init__.py`` runs, every module imports normally, and both the pure-logic
  tests and the HA-dependent tests execute. On Windows we additionally work
  around the harness's socket/event-loop guards (see below).

* **HA absent** (the lightweight CI matrix on 3.12/3.13, which installs only
  pytest + pytest-cov + pytest-asyncio + aiohttp): pre-register the top-level
  package as a stub whose ``__path__`` points at the real source dir. Importing
  a submodule (e.g. ``...api.protocols.crc``) then loads the real file and
  resolves relative imports, but the HA-importing top-level ``__init__.py``
  never executes. HA-dependent test files self-skip via
  ``pytest.importorskip("homeassistant")`` /
  ``pytest.importorskip("pytest_homeassistant_custom_component.common")``.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from typing import Any

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PKG = _ROOT / "custom_components" / "dess_monitor"

_HA_AVAILABLE = importlib.util.find_spec("homeassistant") is not None

# ``test_protocols_smoke.py`` is a standalone runner: module-level assertions
# ending in ``sys.exit(0)``. Importing it during collection would abort the run.
# Its coverage lives in ``test_protocols_codec.py``; run it directly with
# ``python tests/test_protocols_smoke.py`` for the legacy output.
collect_ignore = ["test_protocols_smoke.py"]


def _stub_package(fullname: str, path: pathlib.Path) -> None:
    """Register ``fullname`` as a namespace-style package rooted at ``path``
    without executing its real ``__init__.py``."""
    if fullname in sys.modules:
        return
    mod = types.ModuleType(fullname)
    mod.__path__ = [str(path)]
    mod.__package__ = fullname
    sys.modules[fullname] = mod


if not _HA_AVAILABLE:
    # Only the TOP-LEVEL ``__init__.py`` imports Home Assistant; the ``api``,
    # ``sdk`` and ``mapping`` subpackages are HA-free. Stubbing the two parent
    # packages lets a pure-logic submodule import the real file without running
    # the HA-importing top-level ``__init__.py``.
    _stub_package("custom_components", _ROOT / "custom_components")
    _stub_package("custom_components.dess_monitor", _PKG)


# ---------------------------------------------------------------------------
# HA-present-only setup: Windows workarounds + phacc fixtures.
# ---------------------------------------------------------------------------
if _HA_AVAILABLE:
    import asyncio
    import asyncio.events as _asyncio_events

    import pytest_socket

    if sys.platform == "win32":
        # pytest-homeassistant-custom-component calls
        # ``pytest_socket.disable_socket`` per test. On native Windows that
        # backfires: HA's policy builds a ``ProactorEventLoop`` whose self-pipe
        # is a loopback ``socketpair`` (AF_INET, not AF_UNIX), so the harness
        # can't create its own event loop. Neutralise the blocker — these tests
        # always mock the SDK/aiohttp layer, so nothing opens a real socket.
        pytest_socket.disable_socket = lambda *args, **kwargs: None  # type: ignore[assignment]

        # The harness's autouse ``mock_zeroconf_resolver`` builds an
        # ``aiohttp.AsyncResolver`` → ``aiodns.DNSResolver``, and aiodns refuses
        # to run on anything but a ``SelectorEventLoop`` on Windows. phacc neuters
        # ``asyncio.set_event_loop_policy`` to a no-op at import; restore it and
        # install a selector policy before any session loop is created.
        asyncio.set_event_loop_policy = _asyncio_events.set_event_loop_policy  # type: ignore[assignment]
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

    @pytest.fixture(scope="session")
    def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
        """Loop policy pytest-asyncio uses for the session — selector on Windows."""
        if sys.platform == "win32":
            return asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        return asyncio.get_event_loop_policy()

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
        """Make HA discover the integration under ``custom_components/`` for every
        HA test. ``enable_custom_integrations`` is supplied by
        pytest-homeassistant-custom-component."""
        return None


# ---------------------------------------------------------------------------
# Plain data fixtures (no HA needed; harmless to define in both modes).
# ---------------------------------------------------------------------------
@pytest.fixture
def config_entry_data() -> dict[str, str]:
    """Minimal ``entry.data`` accepted by ``async_setup_entry``."""
    return {
        "username": "tester",
        "password_hash": "0" * 40,  # SHA1 hex placeholder
    }


@pytest.fixture
def device_identity_dict() -> dict[str, Any]:
    """A representative ``DeviceIdentity`` payload as the cloud returns it."""
    return {
        "devaddr": 1,
        "devcode": 2376,
        "pn": "W0030000000000",
        "sn": "96320000000000",
    }
