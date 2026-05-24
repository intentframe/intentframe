"""Terminal bundle AE prompt routing helpers."""

from __future__ import annotations

_NETWORK_MUTATION_SUBTAGS: frozenset[str] = frozenset({
    "http_mutate",
    "http_download",
    "port_scan",
    "file_transfer",
})

_NETWORK_PROBE_SUBTAGS: frozenset[str] = frozenset({
    "icmp",
    "trace",
    "dns",
    "whois",
    "http_get",
})

_NETWORK_PROBE_PREFIX = "capability:network_probe:"


def has_network_mutation(caps: tuple[str, ...]) -> bool:
    for cap in caps:
        if not cap.startswith(_NETWORK_PROBE_PREFIX):
            continue
        sub = cap[len(_NETWORK_PROBE_PREFIX):]
        if sub in _NETWORK_MUTATION_SUBTAGS:
            return True
    return False


def has_network_probe(caps: tuple[str, ...]) -> bool:
    for cap in caps:
        if not cap.startswith(_NETWORK_PROBE_PREFIX):
            continue
        sub = cap[len(_NETWORK_PROBE_PREFIX):]
        if sub in _NETWORK_PROBE_SUBTAGS:
            return True
    return False
