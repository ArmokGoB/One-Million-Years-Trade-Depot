# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the capture mod outside the game.

pyMHF and NMS.py only run inside No Man's Sky on Windows, but their struct
definitions are plain ctypes. This module stubs the Windows-only packages
they import (MinHook, pymem, pywin32 and friends), so the real NMS.py
structs, hook decorators and pyMHF ``Mod`` class load anywhere. Tests then
build fake game memory with those structs and feed it to the mod.

Needs ``pip install --no-deps nmspy pymhf`` plus typing_extensions,
packaging and tomlkit; see .github/workflows/ci.yml for the pinned versions.
"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
import types
from pathlib import Path

MOD_PATH = Path(__file__).resolve().parents[1] / "system_capture.py"

_STUBBED = [
    "pymem",
    "pymem.pattern",
    "pymem.process",
    "pymem.ressources",
    "pymem.ressources.kernel32",
    "win32gui",
    "win32process",
    "win32api",
    "win32con",
    "pywinctl",
    "keyboard",
    "psutil",
    "questionary",
    "pyrun_injected",
    "pyrun_injected.dllinject",
]


class _Anything:
    """Stands in for any attribute of a stubbed Windows-only module."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Anything()

    def __call__(self, *args, **kwargs):
        return _Anything()


def _stub(name: str, structs: bool = False, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    cache: dict[str, type] = {}

    def lookup(attr: str):
        if attr.startswith("__"):
            raise AttributeError(attr)
        if not structs:
            return _Anything
        if attr not in cache:  # used in ctypes argtypes, so must be a real ctypes type
            cache[attr] = type(attr, (ctypes.Structure,), {"_fields_": [("_unused", ctypes.c_uint64)]})
        return cache[attr]

    module.__getattr__ = lookup
    sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent in sys.modules:
        setattr(sys.modules[parent], child, module)
    return module


def install() -> None:
    """Make ``pymhf`` and ``nmspy`` importable off Windows. Safe to call twice."""
    if "pymhf" in sys.modules and getattr(sys.modules["pymhf"], "_trade_depot_harness", False):
        return
    if sys.platform != "win32":

        class MinHook:
            def __init__(self, *args, **kwargs):
                pass

        cyminhook = _stub(
            "cyminhook", MinHook=MinHook, queue_enable=lambda hook: None, apply_queued=lambda: None
        )
        cyminhook._cyminhook = types.SimpleNamespace(Error=Exception, Status=_Anything())
        for name in _STUBBED:
            _stub(name)
        _stub(
            "pymem.exception",
            ProcessNotFound=Exception,
            CouldNotOpenProcess=Exception,
            MemoryReadError=Exception,
        )
        _stub("pymem.ressources.structure", structs=True)
        ctypes.windll = _Anything()
        ctypes.WinDLL = _Anything

    # Load pyMHF's submodules without its package __init__, which starts the
    # injector machinery. The mod only needs Mod, the decorators and structs.
    spec = importlib.util.find_spec("pymhf")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("pymhf isn't installed; see the docstring of mods/tests/harness.py")
    package = types.ModuleType("pymhf")
    package.__path__ = list(spec.submodule_search_locations)
    package.__spec__ = spec
    package.__file__ = spec.origin
    package._trade_depot_harness = True
    sys.modules["pymhf"] = package
    from pymhf.core.mod_loader import Mod, ModState

    package.Mod = Mod
    package.ModState = ModState
    try:
        from importlib import metadata

        package.__version__ = metadata.version("pymhf")
    except Exception:
        package.__version__ = "0"


def load_mod(name: str = "system_capture_under_test") -> types.ModuleType:
    """Import a fresh copy of mods/system_capture.py."""
    install()
    spec = importlib.util.spec_from_file_location(name, MOD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeMemory:
    """A read_memory() replacement that only reads buffers the test allocated.

    Anything else returns None, as ReadProcessMemory does for an address that
    isn't mapped, so tests can hand the mod bad pointers safely.
    """

    def __init__(self):
        self._regions: list[tuple[int, int, object]] = []

    def keep(self, buffer) -> int:
        address = ctypes.addressof(buffer)
        self._regions.append((address, ctypes.sizeof(buffer), buffer))
        return address

    def read(self, address: int, size: int) -> bytes | None:
        if not address or size <= 0:
            return None
        for start, length, _ in self._regions:
            if start <= address and address + size <= start + length:
                return ctypes.string_at(address, size)
        return None
