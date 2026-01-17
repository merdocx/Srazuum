"""Утилита для проверки IP-адресов YooKassa."""

import ipaddress
from typing import List, Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Официальные IP-адреса YooKassa
YOOKASSA_IP_RANGES = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",  # Одиночный IP
    "77.75.156.35/32",  # Одиночный IP
    "77.75.154.128/25",
    "2a02:5180::/32",  # IPv6
]

# Предкомпилированные сети для быстрой проверки
_compiled_networks: Optional[List[ipaddress.IPv4Network | ipaddress.IPv6Network]] = None


def _compile_networks() -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Скомпилировать сети для проверки IP."""
    global _compiled_networks
    if _compiled_networks is None:
        _compiled_networks = []
        for ip_range in YOOKASSA_IP_RANGES:
            try:
                _compiled_networks.append(ipaddress.ip_network(ip_range, strict=False))
            except ValueError as e:
                logger.error(f"invalid_ip_range: {ip_range}, error={str(e)}")
    return _compiled_networks


def is_yookassa_ip(ip_address: str) -> bool:
    """
    Проверить, принадлежит ли IP-адрес YooKassa.

    Args:
        ip_address: IP-адрес для проверки (может быть IPv4 или IPv6)

    Returns:
        True если IP принадлежит YooKassa, False иначе
    """
    try:
        ip = ipaddress.ip_address(ip_address)
        networks = _compile_networks()
        for network in networks:
            if ip in network:
                return True
        return False
    except ValueError:
        # Некорректный IP-адрес
        logger.warning(f"invalid_ip_address: {ip_address}")
        return False


def get_client_ip(request) -> str:
    """
    Получить IP-адрес клиента из запроса.

    Args:
        request: FastAPI Request объект

    Returns:
        IP-адрес клиента
    """
    # Проверяем заголовок X-Forwarded-For (если запрос идет через прокси)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Берем первый IP из списка (оригинальный клиент)
        return forwarded_for.split(",")[0].strip()

    # Проверяем заголовок X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Используем client.host (может быть прокси IP)
    return request.client.host if request.client else "unknown"
