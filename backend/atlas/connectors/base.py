"""Cliente HTTP comum aos conectores: repetição com recuo exponencial e cache bruto em disco.

O cache em `data/raw/` guarda a resposta original da fonte, o que torna as cargas
reprodutíveis e evita sobrecarregar serviços públicos em reexecuções.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx

from ..config import settings
from ..log import ctx, get_logger

log = get_logger("http")


class SourceUnavailable(RuntimeError):
    """A fonte oficial não respondeu após as tentativas configuradas."""


class NotPublished(RuntimeError):
    """O recurso solicitado não existe na fonte (ex.: mês ainda não divulgado)."""


_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=settings.http_timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "gzip"},
        )
    return _client


def _cache_path(namespace: str, key: str, suffix: str) -> Path:
    d = settings.raw_dir / namespace
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:120]
    digest = hashlib.sha1(key.encode()).hexdigest()[:10]
    return d / f"{safe}__{digest}{suffix}"


def fetch(
    url: str,
    *,
    namespace: str,
    cache_key: str | None = None,
    suffix: str = ".json",
    refresh: bool = False,
    not_found_ok: bool = False,
) -> bytes:
    """Baixa `url` (GET) e devolve os bytes, usando o cache bruto quando existir."""
    path = _cache_path(namespace, cache_key or url, suffix)
    if path.exists() and not refresh:
        return path.read_bytes()
    last: Exception | None = None
    for attempt in range(settings.http_retries):
        try:
            r = client().get(url)
            if r.status_code == 404:
                raise NotPublished(url)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if suffix == ".zip" and "html" in ctype:
                raise NotPublished(url)
            path.write_bytes(r.content)
            return r.content
        except NotPublished:
            if not_found_ok:
                raise
            raise
        except (httpx.HTTPError, OSError) as e:
            last = e
            wait = 2**attempt * 1.5
            log.warning("falha de rede; nova tentativa", extra=ctx(url=url, tentativa=attempt + 1, espera_s=wait, erro=str(e)[:200]))
            time.sleep(wait)
    raise SourceUnavailable(f"{url}: {last}")
