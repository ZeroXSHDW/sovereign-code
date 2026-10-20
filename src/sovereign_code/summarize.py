"""Read a local file or URL and ask the local model for a summary."""

from __future__ import annotations

from pathlib import Path

import httpx

MAX_CHARS = 24000

SYSTEM_PROMPT = (
    "Summarize the following content concisely but completely, preserving the key "
    "facts, names, and any instructions. Use plain paragraphs or a short bullet list."
)


class SourceError(ValueError):
    """The file or URL could not be read."""


def read_text_source(
    path: str | None = None,
    url: str | None = None,
    max_chars: int = MAX_CHARS,
) -> str:
    if path:
        data = Path(path).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
    elif url:
        try:
            response = httpx.get(url, timeout=20.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceError(f"could not fetch {url}: {exc.__class__.__name__}") from exc
        text = response.text
    else:
        raise SourceError("give a file path or --url")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[truncated]"
    return text


def complete(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.2,
    timeout: float = 180.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    base = base_url.rstrip("/")
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0), transport=transport
        ) as client:
            response = client.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
            )
    except httpx.HTTPError as exc:
        raise SourceError(f"gateway unreachable: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise SourceError(f"gateway HTTP {response.status_code}")
    try:
        return response.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise SourceError("gateway returned a malformed completion") from exc


def summarize_text(
    base_url: str,
    model: str,
    text: str,
    max_tokens: int = 512,
    timeout: float = 180.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    return complete(
        base_url,
        model,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        max_tokens=max_tokens,
        timeout=timeout,
        transport=transport,
    )
