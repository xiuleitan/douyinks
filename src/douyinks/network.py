import ipaddress
import socket


def get_lan_ips() -> list[str]:
    candidates: list[str] = []
    candidates.extend(_ips_from_udp_routes())
    candidates.extend(_ips_from_hostname())
    return unique_lan_ips(candidates)


def unique_lan_ips(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ips: list[str] = []
    for value in values:
        if value in seen or not is_private_ipv4(value):
            continue
        seen.add(value)
        ips.append(value)
    return ips


def is_private_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local


def _ips_from_udp_routes() -> list[str]:
    ips: list[str] = []
    for target in ("223.5.5.5", "1.1.1.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            ips.append(sock.getsockname()[0])
        except OSError:
            pass
        finally:
            sock.close()
    return ips


def _ips_from_hostname() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return ips
    for info in infos:
        ips.append(info[4][0])
    return ips
