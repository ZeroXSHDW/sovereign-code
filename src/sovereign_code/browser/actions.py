"""Structured browser actions, URL policy, and safety checks."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

ALLOWED_KEYS = {
    "Enter",
    "Tab",
    "Escape",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "PageUp",
    "PageDown",
    "Home",
    "End",
    "Space",
    "Backspace",
}

ACTION_KINDS = {
    "navigate",
    "click",
    "fill",
    "select",
    "press",
    "scroll",
    "wait",
    "extract",
    "handoff",
    "done",
}

DESTRUCTIVE = re.compile(
    r"\b(buy|purchase|pay|checkout|order|delete|remove|send|submit|confirm|"
    r"subscribe|unsubscribe|transfer|withdraw|book|reserve|accept|agree|post|"
    r"publish|delete account|close account)\b",
    re.IGNORECASE,
)

PRIVATE_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}


class ActionError(ValueError):
    """The model produced an action that is not valid JSON or not supported."""


class PolicyError(ValueError):
    """The action would leave the allowed browsing policy."""


@dataclass(frozen=True)
class Action:
    kind: str
    url: str = ""
    target: int | None = None
    text: str = ""
    key: str = ""
    value: str = ""
    direction: str = "down"
    amount: int = 1
    seconds: float = 1.0
    summary: str = ""
    reason: str = ""

    def as_dict(self) -> dict:
        defaults = {
            "url": "",
            "target": None,
            "text": "",
            "key": "",
            "value": "",
            "direction": "down",
            "amount": 1,
            "seconds": 1.0,
            "summary": "",
            "reason": "",
        }
        data: dict = {"action": self.kind}
        for field, default in defaults.items():
            value = getattr(self, field)
            if value != default:
                data["id" if field == "target" else field] = value
        return data


@dataclass(frozen=True)
class BrowserPolicy:
    allow_local: bool = False
    allowed_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_domains",
            tuple(
                domain.strip().lower().lstrip(".")
                for domain in self.allowed_domains
                if domain.strip()
            ),
        )


def _first_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        raise ActionError("no JSON object in model reply")
    try:
        data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise ActionError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ActionError("model reply is not a JSON object")
    return data


def _require_int(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ActionError(f"`{key}` must be a non-negative integer")
    return value


def parse_action(payload: str | dict) -> Action:
    """Parse one model reply into a validated Action."""
    data = _first_json_object(payload) if isinstance(payload, str) else dict(payload)
    kind = str(data.get("action") or data.get("kind") or "").strip().lower()
    if kind not in ACTION_KINDS:
        raise ActionError(f"unknown action `{kind or 'missing'}`")

    if kind == "navigate":
        url = str(data.get("url") or "").strip()
        if not url:
            raise ActionError("navigate needs a url")
        return Action(kind, url=url)
    if kind in {"click", "fill", "select"}:
        target = _require_int(data, "id")
        if kind == "click":
            return Action(kind, target=target)
        if kind == "fill":
            return Action(kind, target=target, text=str(data.get("text") or ""))
        value = str(data.get("value") or "")
        if not value:
            raise ActionError("select needs a value")
        return Action(kind, target=target, value=value)
    if kind == "press":
        key = str(data.get("key") or "").strip()
        if key not in ALLOWED_KEYS:
            raise ActionError(f"unsupported key `{key}`")
        return Action(kind, key=key)
    if kind == "scroll":
        direction = str(data.get("direction") or "down").lower()
        if direction not in {"up", "down", "top", "bottom"}:
            raise ActionError("scroll direction must be up/down/top/bottom")
        amount = data.get("amount", 1)
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ActionError("scroll amount must be an integer")
        amount = max(1, min(20, amount))
        return Action(kind, direction=direction, amount=amount)
    if kind == "wait":
        seconds = data.get("seconds", 1)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ActionError("wait seconds must be a number")
        return Action(kind, seconds=max(0.0, min(5.0, float(seconds))))
    if kind == "extract":
        target = data.get("id")
        if target is not None:
            target = _require_int(data, "id")
        return Action(kind, target=target)
    if kind == "handoff":
        return Action(kind, reason=str(data.get("reason") or "human review needed"))
    return Action(kind, summary=str(data.get("summary") or "Task complete"))


def _is_private_host(host: str) -> bool:
    if host in PRIVATE_HOSTS or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def check_url(url: str, policy: BrowserPolicy, base: str | None = None) -> str:
    """Normalise a URL and enforce scheme, credential, domain, and private-net rules."""
    raw = str(url or "").strip()
    if not raw or len(raw) > 2048:
        raise PolicyError("empty or overlong URL")
    if base and not urlparse(raw).scheme:
        raw = urljoin(base, raw)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise PolicyError("only http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise PolicyError("URLs with embedded credentials are not allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise PolicyError("URL has no host")
    if _is_private_host(host) and not policy.allow_local:
        raise PolicyError("local and private addresses need --allow-local")
    if policy.allowed_domains and not any(
        host == domain or host.endswith("." + domain) for domain in policy.allowed_domains
    ):
        allowed = ", ".join(policy.allowed_domains)
        raise PolicyError(f"`{host}` is outside --allow-domain ({allowed})")
    return parsed.geturl()


def is_destructive(text: str) -> bool:
    return bool(DESTRUCTIVE.search(text or ""))
