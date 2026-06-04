from __future__ import annotations

from typing import List, Optional

from .sandbox import SandboxBackend


class SandboxNotAvailable(Exception):
    """Raised when a resolution asks for a tier this host can't provide.
    Names the missing backend so the operator sees what to install."""


class SandboxRegistry:
    def __init__(self) -> None:
        self._by_name: dict = {}

    def register(self, backend: SandboxBackend) -> None:
        self._by_name[backend.name] = backend

    def backends(self) -> List[SandboxBackend]:
        return sorted(
            self._by_name.values(),
            key=lambda b: b.capabilities().isolation_tier,
            reverse=True,
        )

    def resolve(self, override: Optional[str]) -> SandboxBackend:
        if override is not None:
            b = self._by_name.get(override)
            if b is None:
                raise SandboxNotAvailable(
                    f"sandbox tier '{override}' not available on this host "
                    f"(present: {sorted(self._by_name)})"
                )
            return b
        avail = self.backends()
        if not avail:
            raise SandboxNotAvailable("no sandbox backend available")
        return avail[0]


_current: Optional[SandboxRegistry] = None


def _set_current(reg: SandboxRegistry) -> None:
    global _current
    _current = reg


def get_current_sandbox_registry() -> SandboxRegistry:
    if _current is None:
        raise RuntimeError(
            "sandbox registry not initialized — detect_sandboxes() must run at startup"
        )
    return _current
