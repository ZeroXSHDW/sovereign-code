"""Structured browser actions, URL policy, and safety checks."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from ..errors import ActionError, PolicyError

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

# Curated list of labels that name an action the user cannot take back, or
# that commits them to something: spending money, sending data, destroying an
# account, or confirming a dialog whose contents the model never read.
# The list errs towards asking, because a confirmation prompt is cheap while
# an unwanted purchase, message, or deletion is not.
DESTRUCTIVE = re.compile(
    r"\b(buy|purchase|pay|checkout|order|delete|remove|send|submit|confirm|"
    r"subscribe|unsubscribe|transfer|withdraw|book|reserve|accept|agree|post|"
    r"publish|revoke|reset|terminate|uninstall|destroy|drop|cancel|continue|"
    r"upgrade|apply|yes|delete account|close account|sign out)\b",
    re.IGNORECASE,
)

# A bare "OK" confirms whatever dialog happens to be open, so it counts as
# destructive on its own. It is kept out of the word list above because the
# letters "ok" also show up inside harmless labels such as "OK Google".
OK_LABEL = re.compile(r"^ok[\s.!?]*$", re.IGNORECASE)

# Keys that can activate the control the browser is on: Enter submits the
# form around the focused field, Space presses the focused button.
SUBMIT_KEYS = frozenset({"Enter", "Space"})

PRIVATE_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104 - listed so it is treated as a private address
    "::1",
}


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
        target_id = data.get("id")
        if target_id is not None:
            target_id = _require_int(data, "id")
        return Action(kind, target=target_id if target_id is None else int(target_id))
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
    """True when a visible label names an irreversible or committing action."""
    label = (text or "").strip()
    if not label:
        return False
    return bool(OK_LABEL.match(label) or DESTRUCTIVE.search(label))


def is_submit_control(tag: str, control_type: str = "") -> bool:
    """True when a control can submit the form it belongs to.

    A bare ``<button>`` defaults to ``type="submit"``, so an icon-only
    button inside a form submits it just as a labelled one would.
    """
    tag = (tag or "").strip().lower()
    control_type = (control_type or "").strip().lower()
    if tag == "button":
        return control_type in {"", "submit"}
    if tag == "input":
        return control_type in {"submit", "image"}
    return False


def needs_confirmation(label: str, tag: str = "", control_type: str = "") -> bool:
    """True when a click on this control has to be confirmed by the user.

    A control with a readable label is destructive when that label names an
    irreversible action. A control without a label (an icon-only button) is
    destructive when it can submit a form, because the label is exactly the
    thing the model cannot read.
    """
    text = (label or "").strip()
    if text:
        return is_destructive(text)
    return is_submit_control(tag, control_type)
