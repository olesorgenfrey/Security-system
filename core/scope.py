"""Scope-Konzept (docs/architecture.md §6): legt hart fest, welche Assets
gescannt oder von der Response-Engine angefasst werden dürfen.

Fail-closed: alles, was nicht explizit in `config/scope.yaml` gelistet ist,
gilt als außerhalb des Scopes. Scanner (Phase 3) und Response-Engine
(Phase 5) MÜSSEN vor jeder Aktion `assert_*_in_scope` aufrufen.
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from pathlib import Path

import yaml
from pydantic import BaseModel

from core.config import get_settings

IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


class OutOfScopeError(Exception):
    """Ausgelöst, wenn eine Aktion ein Ziel außerhalb des erlaubten Scopes betrifft."""


class ScopeConfig(BaseModel):
    allowed_networks: list[str] = []
    """CIDR-Bereiche, z.B. '10.0.0.0/24' oder '127.0.0.1/32'."""
    allowed_hosts: list[str] = []
    """Hostnamen, die zusätzlich zu/statt IP-Bereichen erlaubt sind."""


class Scope:
    def __init__(self, config: ScopeConfig) -> None:
        self._config = config
        self._networks: list[IPNetwork] = [ip_network(n) for n in config.allowed_networks]
        self._hosts = set(config.allowed_hosts)

    def is_ip_in_scope(self, ip: str) -> bool:
        addr = ip_address(ip)
        return any(addr in net for net in self._networks)

    def is_host_in_scope(self, hostname: str) -> bool:
        return hostname in self._hosts

    def assert_ip_in_scope(self, ip: str) -> None:
        if not self.is_ip_in_scope(ip):
            raise OutOfScopeError(f"IP {ip} ist nicht im konfigurierten Scope (config/scope.yaml)")

    def assert_host_in_scope(self, hostname: str) -> None:
        if not self.is_host_in_scope(hostname):
            raise OutOfScopeError(
                f"Host {hostname!r} ist nicht im konfigurierten Scope (config/scope.yaml)"
            )

    @classmethod
    def load(cls, path: Path) -> Scope:
        if not path.exists():
            return cls(ScopeConfig())
        data = yaml.safe_load(path.read_text()) or {}
        return cls(ScopeConfig.model_validate(data))


@lru_cache
def get_scope() -> Scope:
    return Scope.load(Path(get_settings().scope_file))
