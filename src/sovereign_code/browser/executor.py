"""Playwright browser session: observe a page and execute one structured action."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..errors import BrowserError, SensitiveFieldError
from .actions import (
    SUBMIT_KEYS,
    Action,
    BrowserPolicy,
    PolicyError,
    check_url,
    needs_confirmation,
)

CAPTCHA_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "are you a robot",
    "i'm not a robot",
    "unusual traffic",
    "checking your browser",
    "cf-challenge",
    "challenge-platform",
)

# One pattern drives both the observation JavaScript and the fill refusal, so
# the two can never drift apart. The terms name the fields that carry a
# one-time secret or payment data; they are matched with lookarounds rather
# than ``\b`` so that an underscore still separates words ("otp_code").
SENSITIVE_PATTERN = (
    r"password|pass[-_ ]?phrase|pass[-_ ]?code|one[-_ ]?time|"
    r"(?<![a-z0-9])otp(?![a-z0-9])|(?<![a-z0-9])pin(?![a-z0-9])|"
    r"(?<![a-z0-9])cvv(?![a-z0-9])|(?<![a-z0-9])cvc(?![a-z0-9])|"
    r"(?<![a-z0-9])card(?![a-z0-9])|card[-_ ]?number|"
    r"(?<![a-z0-9])iban(?![a-z0-9])|(?<![a-z0-9])ssn(?![a-z0-9])|"
    r"security[-_ ]?code|verification[-_ ]?code"
)
SENSITIVE = re.compile(SENSITIVE_PATTERN, re.IGNORECASE)

_OBSERVE_JS_TEMPLATE = """
() => {
  document.querySelectorAll('[data-sovereign-id]').forEach(
    (el) => el.removeAttribute('data-sovereign-id')
  );
  const selector = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"]';
  const nodes = Array.from(document.querySelectorAll(selector));
  const visible = nodes.filter((el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      rect.width > 1 &&
      rect.height > 1 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      style.opacity !== '0'
    );
  }).slice(0, 60);
  visible.forEach((el, i) => el.setAttribute('data-sovereign-id', String(i)));
  const sensitivePattern = /__SENSITIVE__/i;
  const elements = visible.map((el, i) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const tag = el.tagName.toLowerCase();
    const blob = [
      type,
      el.name,
      el.id,
      el.getAttribute('autocomplete'),
      el.getAttribute('placeholder')
    ].join(' ');
    // A secret field holds a password, a one-time code, or card data. It is
    // flagged so the agent refuses to fill it, and its value is never read
    // out: the observation goes straight to the planner model.
    const sensitive = sensitivePattern.test(blob);
    const label = (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.innerText ||
      ''
    );
    const name = (
      label ||
      el.getAttribute('name') ||
      (sensitive ? '' : String(el.value || '')) ||
      el.id ||
      ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 120);
    return {
      id: i,
      tag: tag,
      type: type || null,
      role: el.getAttribute('role') || null,
      name: name,
      value: sensitive ? '' : String(el.value || '').slice(0, 80),
      href: tag === 'a' ? String(el.href || '').slice(0, 200) : null,
      disabled: Boolean(el.disabled),
      sensitive: sensitive
    };
  });
  const bodyText = document.body ? document.body.innerText : '';
  return {
    url: location.href,
    title: document.title,
    text: bodyText.slice(0, 4000),
    elements: elements
  };
}
"""

# The pattern is injected so the page and the harness agree on what a secret
# field is; a stale copy here would leak a value the harness refuses to fill.
OBSERVE_JS = _OBSERVE_JS_TEMPLATE.replace("__SENSITIVE__", SENSITIVE_PATTERN)

_PRESS_RISK_JS_TEMPLATE = """
() => {
  const sensitivePattern = /__SENSITIVE__/i;
  const isSubmitControl = (el) => {
    if (!el || !el.tagName) {
      return false;
    }
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'button') {
      return type === '' || type === 'submit';
    }
    if (tag === 'input') {
      return type === 'submit' || type === 'image';
    }
    return false;
  };
  const focusedSubmit = isSubmitControl(document.activeElement);
  const forms = Array.from(document.forms || []);
  for (const form of forms) {
    const fields = Array.from(form.querySelectorAll('input, textarea'));
    for (const field of fields) {
      const blob = [
        field.getAttribute('type') || '',
        field.name || '',
        field.id || '',
        field.getAttribute('autocomplete') || '',
        field.getAttribute('placeholder') || ''
      ].join(' ');
      if (!sensitivePattern.test(blob)) {
        continue;
      }
      // The value is still sitting in the form, so the form has not been
      // submitted yet and pressing Enter would send the secret.
      if (String(field.value || '').length > 0) {
        return {credential: true, focusedSubmit: focusedSubmit};
      }
    }
  }
  return {credential: false, focusedSubmit: focusedSubmit};
}
"""

PRESS_RISK_JS = _PRESS_RISK_JS_TEMPLATE.replace("__SENSITIVE__", SENSITIVE_PATTERN)

_CONTROL_INFO_JS = """
(el) => {
  const tag = (el.tagName || '').toLowerCase();
  const type = (el.getAttribute('type') || '').toLowerCase();
  const text = (el.innerText || '').trim();
  const label = (
    text ||
    el.getAttribute('aria-label') ||
    el.getAttribute('value') ||
    el.getAttribute('title') ||
    ''
  );
  return {
    tag: tag,
    type: type,
    label: label.replace(/\\s+/g, ' ').trim().slice(0, 120)
  };
}
"""


def chromium_path() -> Path | None:
    """Return Playwright's Chromium executable if it is installed, else None."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            candidate = Path(playwright.chromium.executable_path)
        return candidate if candidate.exists() else None
    except Exception:
        return None


def detect_captcha(observation: dict) -> bool:
    blob = " ".join(
        [
            str(observation.get("url") or ""),
            str(observation.get("title") or ""),
            str(observation.get("text") or "")[:4000],
        ]
    ).lower()
    return any(marker in blob for marker in CAPTCHA_MARKERS)


class BrowserSession:
    """A visible, persistent Chromium profile with no stealth patches."""

    def __init__(
        self,
        profile_dir: Path,
        policy: BrowserPolicy,
        headless: bool = False,
        timeout_ms: int = 60000,
    ) -> None:
        self.profile_dir = profile_dir
        self.policy = policy
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self.context: Any = None
        self.page: Any = None
        self._blocked_url: str | None = None
        self._last_allowed_url: str | None = None

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def start(self, url: str | None = None) -> None:
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.profile_dir, 0o700)
        except OSError:
            pass
        self._playwright = sync_playwright().start()
        try:
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                args=["--no-first-run", "--no-default-browser-check"],
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(self.timeout_ms)
            self._install_policy_guard()
            if url:
                self.goto(url)
        except Exception:
            self.close()
            raise

    def _install_policy_guard(self) -> None:
        """Abort top-level navigations that would leave the policy.

        Checking the URL after the fact is too late: the request already told
        the off-policy host that the visit happened. Aborting the request is
        what actually keeps the browsing inside the allowlist.
        """
        if self.context is None:
            return

        def guard(route, request=None) -> None:
            target = ""
            try:
                req = request if request is not None else route.request
                target = str(req.url)
                if self._is_main_frame_navigation(req):
                    check_url(target, self.policy)
            except PolicyError:
                self._blocked_url = target or None
                try:
                    route.abort()
                except Exception:
                    pass
                return
            except Exception:
                pass
            try:
                route.continue_()
            except Exception:
                pass

        try:
            self.context.route("**/*", guard)
        except Exception:
            pass

    @staticmethod
    def _is_main_frame_navigation(request) -> bool:
        """True for a top-level page load, false for a frame or a subresource."""
        try:
            if not request.is_navigation_request():
                return False
            frame = request.frame
        except Exception:
            return False
        try:
            return frame.parent_frame is None
        except Exception:
            return True

    def _failure(self, message: str, exc: Exception) -> Exception:
        """Turn a Playwright error into a policy error when policy blocked it."""
        if self._blocked_url:
            blocked = self._blocked_url
            self._blocked_url = None
            return PolicyError(f"navigation to {blocked} was blocked by the policy")
        return BrowserError(f"{message}: {exc}")

    def _enforce_policy(self, url: str) -> str:
        """Re-check the URL the browser actually reached against the policy.

        The allowlist has to hold for the final URL: a redirect, a link, or a
        form submission all end up somewhere the model never chose.
        """
        if self._blocked_url:
            blocked = self._blocked_url
            self._blocked_url = None
            raise PolicyError(f"navigation to {blocked} was blocked by the policy")
        try:
            checked = check_url(url, self.policy)
        except PolicyError:
            self._restore_last_allowed()
            raise
        self._last_allowed_url = checked
        return checked

    def _restore_last_allowed(self) -> None:
        """Best effort: go back to the last page that was inside the policy."""
        target = self._last_allowed_url
        if not target or self.page is None:
            return
        try:
            self.page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.page.wait_for_timeout(200)
        except Exception:
            pass

    def goto(self, url: str, base: str | None = None) -> str:
        """Navigate to a URL, then re-check the policy on the page we land on."""
        if self.page is None:
            raise BrowserError("browser is not running")
        target = check_url(url, self.policy, base=base or self.page.url)
        self._blocked_url = None
        try:
            self.page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:  # Playwright's error types vary by version
            raise self._failure("navigation failed", exc) from exc
        self.page.wait_for_timeout(400)
        self._enforce_policy(self.page.url)
        return target

    def observe(self) -> dict:
        if self.page is None:
            raise BrowserError("browser is not running")
        try:
            observation = self.page.evaluate(OBSERVE_JS)
        except Exception:
            self.page.wait_for_timeout(400)
            try:
                observation = self.page.evaluate(OBSERVE_JS)
            except Exception as exc:
                raise BrowserError(f"could not read the page: {exc}") from exc
        if not isinstance(observation, dict):
            raise BrowserError("page observation returned no data")
        observation["captcha"] = detect_captcha(observation)
        self._blank_sensitive_values(observation)
        return observation

    @staticmethod
    def _blank_sensitive_values(observation: dict) -> None:
        """Second line of defence: never hand a secret to the caller.

        The observation script already blanks sensitive fields; this keeps
        that promise even if a page reports a value for a field it flagged.
        """
        for element in observation.get("elements") or []:
            if isinstance(element, dict) and element.get("sensitive") and element.get("value"):
                element["value"] = ""

    def _element(self, target: int):
        locator = self.page.locator(f'[data-sovereign-id="{target}"]')
        try:
            count = locator.count()
        except Exception as exc:
            raise BrowserError(f"could not resolve element {target}: {exc}") from exc
        if count == 0:
            raise BrowserError(f"element {target} is stale; observe the page again")
        return locator.first

    def _control_info(self, locator) -> tuple[str, str, str]:
        """Return (tag, type, visible label) for the control behind a locator."""
        try:
            info = locator.evaluate(_CONTROL_INFO_JS)
        except Exception:
            return "", "", ""
        if not isinstance(info, dict):
            return "", "", ""
        tag = str(info.get("tag") or "")
        control_type = str(info.get("type") or "")
        label = str(info.get("label") or "").strip()[:120]
        return tag, control_type, label

    def _fallback_label(self, locator) -> str:
        """Last resort label for a control with no visible text."""
        for attribute in ("name", "placeholder"):
            try:
                value = locator.get_attribute(attribute) or ""
            except Exception:
                value = ""
            if value.strip():
                return value.replace("\n", " ").strip()[:120]
        return ""

    def _label(self, locator, visible: str = "") -> str:
        """Human readable label used in messages and confirmations."""
        if not visible:
            _tag, _control_type, visible = self._control_info(locator)
        return visible or self._fallback_label(locator)

    def _sensitive(self, locator) -> bool:
        try:
            blob = locator.evaluate(
                """(el) => [
                    (el.getAttribute('type') || ''),
                    el.name || '',
                    el.id || '',
                    el.getAttribute('autocomplete') || '',
                    el.getAttribute('placeholder') || ''
                ].join(' ')"""
            )
        except Exception:
            return False
        return bool(SENSITIVE.search(str(blob)))

    def _check_click_target(self, locator, base: str) -> None:
        """Reject a click whose link points straight outside the policy."""
        try:
            href = locator.get_attribute("href")
        except Exception:
            return
        if not href:
            return
        try:
            scheme = urlsplit(href).scheme.lower()
            base_scheme = urlsplit(base).scheme.lower()
        except ValueError:
            return
        if scheme and scheme not in {"http", "https"}:
            # javascript:, mailto:, and tel: never leave the current page.
            return
        if base_scheme not in {"http", "https"}:
            # Nothing to resolve a relative link against.
            return
        check_url(href, self.policy, base=base)

    def _press_risk(self, key: str) -> str:
        """Describe the risk of pressing a key that can submit a form."""
        if key not in SUBMIT_KEYS or self.page is None:
            return ""
        try:
            info = self.page.evaluate(PRESS_RISK_JS)
        except Exception:
            return ""
        if not isinstance(info, dict):
            return ""
        if info.get("credential"):
            return (
                f"Pressing {key} may submit a form that holds a credential "
                "(password, one-time code, or card data)."
            )
        if info.get("focusedSubmit"):
            return f"Pressing {key} may submit the focused form."
        return ""

    def perform(
        self,
        action: Action,
        confirm: Callable[[str], bool] | None = None,
    ) -> dict:
        if self.page is None:
            raise BrowserError("browser is not running")
        self._blocked_url = None

        if action.kind == "navigate":
            target = self.goto(action.url)
            return {"ok": True, "detail": f"navigated to {target}"}

        if action.kind == "click":
            locator = self._element(action.target or 0)
            tag, control_type, visible = self._control_info(locator)
            label = self._label(locator, visible)
            if needs_confirmation(visible, tag, control_type):
                question = (
                    f'Click "{label}"? This may submit, buy, or delete something.'
                    if label
                    else "Click an unnamed control? It may submit a form, "
                    "buy something, or delete something."
                )
                if confirm is None or not confirm(question):
                    return {
                        "ok": False,
                        "cancelled": True,
                        "detail": f'cancelled click on "{label}"' if label else "cancelled click",
                    }
            self._check_click_target(locator, self.page.url)
            locator.scroll_into_view_if_needed()
            try:
                locator.click(timeout=self.timeout_ms)
            except Exception as exc:
                raise self._failure("click failed", exc) from exc
            self.page.wait_for_timeout(700)
            self._enforce_policy(self.page.url)
            return {"ok": True, "detail": f'clicked "{label}"'}

        if action.kind == "fill":
            locator = self._element(action.target or 0)
            if self._sensitive(locator):
                raise SensitiveFieldError(
                    "refusing to fill a password, OTP, or payment field; use handoff"
                )
            try:
                locator.fill(action.text)
            except Exception as exc:
                raise BrowserError(f"fill failed: {exc}") from exc
            return {"ok": True, "detail": f"filled {action.target} with {len(action.text)} chars"}

        if action.kind == "select":
            locator = self._element(action.target or 0)
            try:
                locator.select_option(value=action.value)
            except Exception as exc:
                raise BrowserError(f"select failed: {exc}") from exc
            # The chosen value is not echoed: it can be an account or a token.
            return {"ok": True, "detail": f"selected an option in element {action.target}"}

        if action.kind == "press":
            risk = self._press_risk(action.key)
            if risk:
                if confirm is None or not confirm(risk):
                    return {
                        "ok": False,
                        "cancelled": True,
                        "detail": f"cancelled press of {action.key}",
                    }
            try:
                self.page.keyboard.press(action.key)
            except Exception as exc:
                raise BrowserError(f"press failed: {exc}") from exc
            self.page.wait_for_timeout(400)
            self._enforce_policy(self.page.url)
            return {"ok": True, "detail": f"pressed {action.key}"}

        if action.kind == "scroll":
            if action.direction == "top":
                self.page.evaluate("window.scrollTo(0, 0)")
            elif action.direction == "bottom":
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                delta = 600 * action.amount * (1 if action.direction == "down" else -1)
                self.page.mouse.wheel(0, delta)
            self.page.wait_for_timeout(300)
            return {"ok": True, "detail": f"scrolled {action.direction}"}

        if action.kind == "wait":
            time.sleep(action.seconds)
            return {"ok": True, "detail": f"waited {action.seconds:g}s"}

        if action.kind == "extract":
            text = (
                self._element(action.target).inner_text()
                if action.target is not None
                else self.page.inner_text("body")
            )
            return {"ok": True, "detail": "extracted text", "extract": text[:4000]}

        if action.kind in {"handoff", "done"}:
            return {"ok": True, "detail": action.kind}

        raise BrowserError(f"unsupported action {action.kind}")

    def screenshot(self, dest: Path) -> Path | None:
        if self.page is None:
            return None
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(dest))
            return dest
        except Exception:
            return None

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self.page = None
