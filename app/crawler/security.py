"""
TraceGraph AI — Security & URL Validation Module
Prevents SSRF, DNS rebinding, private network access, cloud metadata exfiltration, and protocol injection.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any, Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Blocked IP Networks for SSRF Defense
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private Class A
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback IPv4
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local & AWS/GCP metadata
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private Class B
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private Class C
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved / Future use
    ipaddress.ip_network("::1/128"),            # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),           # Unique local IPv6
    ipaddress.ip_network("fe80::/10"),          # Link-local IPv6
]

# Explicit cloud metadata hostnames
METADATA_HOSTNAMES = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}


def hostname_matches(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    """Match exact hosts or dot-delimited subdomains, never arbitrary suffixes."""
    host = hostname.rstrip(".").lower()
    for allowed in allowed_hosts:
        candidate = allowed.rstrip(".").lower()
        if host == candidate or host.endswith(f".{candidate}"):
            return True
    return False


def validate_crawl_url(
    url: str,
    allowed_hosts: Iterable[str] | None = None,
    allow_local_fixtures: bool = False,
) -> dict[str, Any]:
    """
    Validate target URL against SSRF, private network, and protocol injection attacks.
    Returns dict with 'valid' (bool), 'reason' (str), 'resolved_ips' (list[str]).
    """
    if not url or not isinstance(url, str):
        return {"valid": False, "reason": "URL must be a non-empty string", "resolved_ips": []}

    url_clean = url.strip()

    try:
        parsed = urlparse(url_clean)
    except Exception as e:
        return {"valid": False, "reason": f"Invalid URL syntax: {e}", "resolved_ips": []}

    # 1. Protocol validation
    if parsed.scheme.lower() not in ("http", "https"):
        return {
            "valid": False,
            "reason": f"Prohibited scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.",
            "resolved_ips": [],
        }

    hostname = parsed.hostname
    if not hostname:
        return {"valid": False, "reason": "URL must contain a valid hostname.", "resolved_ips": []}

    hostname_lower = hostname.lower()

    # 2. Metadata hostname check
    if hostname_lower in METADATA_HOSTNAMES:
        return {
            "valid": False,
            "reason": "Target matches prohibited cloud metadata endpoint.",
            "resolved_ips": [],
        }

    # 3. Local fixture exception is only for direct unit-test construction.
    # It must never be controlled by an HTTP client.
    if allow_local_fixtures and (hostname_lower in ("localhost", "127.0.0.1", "::1")):
        return {"valid": True, "reason": "Local fixture allowed for CI", "resolved_ips": ["127.0.0.1"]}

    if allowed_hosts is not None and not hostname_matches(hostname_lower, allowed_hosts):
        return {
            "valid": False,
            "reason": f"Host '{hostname}' is not in the configured allowlist.",
            "resolved_ips": [],
        }

    # 4. Resolve DNS & Check all IP addresses
    resolved_ips = []
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if ip_str not in resolved_ips:
                resolved_ips.append(ip_str)
    except socket.gaierror as e:
        return {
            "valid": False,
            "reason": f"DNS resolution failed for host '{hostname}': {e}",
            "resolved_ips": [],
        }
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Error resolving target host '{hostname}': {e}",
            "resolved_ips": [],
        }

    if not resolved_ips:
        return {
            "valid": False,
            "reason": f"No IP addresses resolved for hostname '{hostname}'",
            "resolved_ips": [],
        }

    # 5. Check resolved IP addresses against private / loopback / metadata ranges
    for ip_str in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            for net in BLOCKED_NETWORKS:
                if ip_obj in net:
                    return {
                        "valid": False,
                        "reason": f"Hostname '{hostname}' resolves to blocked network address {ip_str} ({net})",
                        "resolved_ips": resolved_ips,
                    }
            if not ip_obj.is_global or ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                return {
                    "valid": False,
                    "reason": f"Hostname '{hostname}' resolves to a non-public IP {ip_str}",
                    "resolved_ips": resolved_ips,
                }
        except ValueError:
            return {
                "valid": False,
                "reason": f"Invalid IP address format encountered: {ip_str}",
                "resolved_ips": resolved_ips,
            }

    return {
        "valid": True,
        "reason": "URL and resolved destination IPs passed all security checks.",
        "resolved_ips": resolved_ips,
        "hostname": hostname,
        "scheme": parsed.scheme,
    }
