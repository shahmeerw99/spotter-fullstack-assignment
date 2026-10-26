"""One shared HTTP session with timeouts and clean error mapping for every external call."""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

from .errors import UpstreamError, UpstreamTimeout

logger = logging.getLogger("routing")

_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=16))


def get_json(url: str, params: dict | None = None, service: str = "external API"):
    try:
        resp = _session.get(
            url,
            params=params,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise UpstreamTimeout(f"{service} did not respond in time. Please try again.") from exc
    except requests.RequestException as exc:
        raise UpstreamError(f"Could not reach {service}.") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamError(f"{service} returned an invalid response (HTTP {resp.status_code}).") from exc
    if resp.status_code >= 400:
        detail = (data.get("message") or data.get("reason")) if isinstance(data, dict) else None
        logger.warning("%s HTTP %s: %s", service, resp.status_code, detail)
    return data, resp.status_code
