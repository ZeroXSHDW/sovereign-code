"""Playwright browser session: observe a page and execute one structured action."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable

from .actions import Action, BrowserPolicy, PolicyError, check_url, is_destructive

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

SENSITIVE = re.compile(
    r"password|passcode|otp|one-time|cvv|cvc|card.?number|iban|ssn", re.IGNORECASE
)

OBSERVE_JS = """
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
  const elements = visible.map((el, i) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const tag = el.tagName.toLowerCase();
    const blob = [
      type,
      el.name,
      el.id,
      el.getAttribute('autocomplete'),
      el.getAttribute('placeholder'),
    ].join(' ');
    const name = (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.innerText ||
      el.value ||
      el.getAttribute('name') ||
      el.id ||
      ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 120);
    return {
      id: i,
      tag: tag,
      type: type || null,
      role: el.getAttribute('role') || null,
      name: name,
      value: type === 'password' ? '' : String(el.value || '').slice(0, 80),
      href: tag === 'a' ? String(el.href || '').slice(0, 200) : null,
      disabled: Boolean(el.disabled),
      sensitive:
        type === 'password' ||
        /password|passcode|otp|one-time|cvv|cvc|card.?number|iban|ssn/i.test(blob),
    };
  });
  const bodyText = document.body ? document.body.innerText : '';
  return {
    url: location.href,
    title: document.title,
    text: bodyText.slice(0, 4000),
    elements: elements,
  };
}
"""


class BrowserError(RuntimeError):
    """The page could not be observed or the action could not be executed."""


class SensitiveFieldError(BrowserError):
    """Refuse to type secrets into password, OTP, or payment fields."""


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
        timeout_ms: int = 15000,
    ) -> None:
        self.profile_dir = profile_dir
        self.policy = policy
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BrowserSession":
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
            if url:
                self.goto(url)
        except Exception:
            self.close()
            raise

    def goto(self, url: str, base: str | None = None) -> str:
        if self.page is None:
            raise BrowserError("browser is not running")
        target = check_url(url, self.policy, base=base or self.page.url)
        try:
            self.page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:  # Playwright's error types vary by version
            raise BrowserError(f"navigation failed: {exc}") from exc
        self.page.wait_for_timeout(400)
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
        return observation

    def _element(self, target: int):
        locator = self.page.locator(f'[data-sovereign-id="{target}"]')
        try:
            count = locator.count()
        except Exception as exc:
            raise BrowserError(f"could not resolve element {target}: {exc}") from exc
        if count == 0:
            raise BrowserError(f"element {target} is stale; observe the page again")
        return locator.first

    def _label(self, locator) -> str:
        try:
            text = locator.inner_text(timeout=1000)
        except Exception:
            text = ""
        if not text.strip():
            for attribute in ("aria-label", "value", "name", "placeholder"):
                try:
                    text = locator.get_attribute(attribute) or ""
                except Exception:
                    text = ""
                if text.strip():
                    break
        return text.replace("\n", " ").strip()[:120]

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

    def perform(
        self,
        action: Action,
        confirm: Callable[[str], bool] | None = None,
    ) -> dict:
        if self.page is None:
            raise BrowserError("browser is not running")

        if action.kind == "navigate":
            target = self.goto(action.url)
            return {"ok": True, "detail": f"navigated to {target}"}

        if action.kind == "click":
            locator = self._element(action.target or 0)
            label = self._label(locator)
            if is_destructive(label):
                if confirm is None or not confirm(
                    f'Click "{label}"? This may submit, buy, or delete something.'
                ):
                    return {
                        "ok": False,
                        "cancelled": True,
                        "detail": f'cancelled click on "{label}"',
                    }
            locator.scroll_into_view_if_needed()
            locator.click(timeout=self.timeout_ms)
            self.page.wait_for_timeout(700)
            return {"ok": True, "detail": f'clicked "{label}"'}

        if action.kind == "fill":
            locator = self._element(action.target or 0)
            if self._sensitive(locator):
                raise SensitiveFieldError(
                    "refusing to fill a password, OTP, or payment field; use handoff"
                )
            locator.fill(action.text)
            return {"ok": True, "detail": f"filled {action.target} with {len(action.text)} chars"}

        if action.kind == "select":
            locator = self._element(action.target or 0)
            locator.select_option(value=action.value)
            return {"ok": True, "detail": f"selected {action.value}"}

        if action.kind == "press":
            self.page.keyboard.press(action.key)
            self.page.wait_for_timeout(400)
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
