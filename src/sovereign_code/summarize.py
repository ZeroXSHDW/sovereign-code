"""Read a local file or URL and ask the local model for a summary."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import httpx

from .browser.actions import BrowserPolicy, PolicyError, check_url
from .errors import SourceError as SourceError
from .http import shared_client

MAX_CHARS = 32000
MAX_REDIRECTS = 5

SYSTEM_PROMPT = (
    "Summarize the following content concisely but completely, preserving the key "
    "facts, names, and any instructions. Use plain paragraphs or a short bullet list."
)


def _fetch(url: str, timeout: float) -> httpx.Response:
    """Fetch a URL, applying the browser's URL policy to every hop.

    Following redirects blindly would let a public URL bounce the fetch to
    ``http://169.254.169.254/`` and read the machine's metadata, or to a
    loopback admin page. Each hop is checked before it is requested.
    """
    policy = BrowserPolicy()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        try:
            current = check_url(current, policy)
        except PolicyError as exc:
            raise SourceError(f"refused to fetch {url}: {exc}") from exc
        try:
            response = shared_client().get(current, timeout=timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise SourceError(f"could not fetch {url}: {exc.__class__.__name__}") from exc
        if not response.is_redirect:
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise SourceError(f"could not fetch {url}: {exc.__class__.__name__}") from exc
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(current, location)
    raise SourceError(f"too many redirects while fetching {url}")


def read_text_source(
    path: str | None = None,
    url: str | None = None,
    max_chars: int = MAX_CHARS,
) -> str:
    if path:
        if Path(path).suffix.lower() == ".pdf":
            from .pdf import read_pdf

            text = read_pdf(path).combined_text()
        else:
            data = Path(path).read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
    elif url:
        text = _fetch(url, timeout=20.0).text
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
        if transport is not None:
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
        else:
            client = shared_client(timeout=timeout, connect=3.0)
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
        # LiteLLM wraps an upstream 402 in a 500, so the useful reason (the
        # Ollama plan or a disabled cloud) is only in the body. Surface it.
        from .cloud import PRO_UPGRADE, plan_required

        detail = response.text.strip().replace("\n", " ")[:240]
        if plan_required(detail):
            # The raw body is a nested LiteLLM/Ollama JSON blob; the actionable
            # part is the plan, not the wrapper.
            message = (
                f"gateway HTTP {response.status_code}: this model needs an "
                f"Ollama Pro plan: {PRO_UPGRADE}"
            )
        else:
            message = f"gateway HTTP {response.status_code}"
            if detail:
                message += f": {detail}"
            if "cloud is disabled" in detail.lower():
                message += " — enable it with: sovereign cloud --enable"
        raise SourceError(message)
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


REPO_PROMPT = (
    "Here is the structure of a codebase. In a few short paragraphs, explain what "
    "this project does, the main components and how they fit together, the primary "
    "entry points, and anything a new contributor must know first. Keep it factual "
    "and ground every claim in the outline below."
)


def summarize_repo(
    base_url: str,
    model: str,
    root: Path,
    max_tokens: int = 700,
    timeout: float = 180.0,
) -> str:
    """Summarize a whole codebase from its repo map and project context."""
    from .memory import project_context
    from .repomap import repo_map

    outline = repo_map(root)
    if not outline.strip():
        raise SourceError(f"no code files found under {root}")
    context = project_context(root)
    parts = [outline]
    if context.strip():
        parts.append(f"# Project instructions\n{context}")
    readme = root / "README.md"
    if readme.is_file():
        # A README is the project's own description; include its head as a hint.
        readme_text = readme.read_text(encoding="utf-8", errors="replace")[:4000]
        parts.append(f"# README (partial)\n{readme_text}")
    body = "\n\n".join(parts)
    return complete(
        base_url,
        model,
        [
            {"role": "system", "content": REPO_PROMPT},
            {"role": "user", "content": body},
        ],
        max_tokens=max_tokens,
        timeout=timeout,
    )
