"""Local-model browser agent: observe, plan one action, execute, repeat."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from ..config import DATA_DIR
from .actions import Action, ActionError, BrowserPolicy, PolicyError, parse_action
from .executor import BrowserError, BrowserSession, SensitiveFieldError

SYSTEM_PROMPT = """\
You are a careful browser operator driving a visible Chromium browser for the user.
Reply with exactly one JSON object and nothing else.

Allowed actions:
{"action":"navigate","url":"https://example.com"}
{"action":"click","id":3}
{"action":"fill","id":4,"text":"..."}
{"action":"select","id":5,"value":"..."}
{"action":"press","key":"Enter"}
{"action":"scroll","direction":"down","amount":1}
{"action":"wait","seconds":1}
{"action":"extract","id":2}
{"action":"handoff","reason":"why the user must take over"}
{"action":"done","summary":"what was accomplished or found"}

Field meanings:
- `text` only belongs to fill (the characters to type). Never put a summary there.
- `id` refers to an element listed under ELEMENTS.
- `summary` belongs to done and carries the answer the user asked for.

Rules:
- One action per reply. Use only element ids listed under ELEMENTS.
- PAGE.text is the visible page. If it already answers the task, return done immediately.
- Never solve, click, or interact with CAPTCHAs or bot checks. Use handoff.
- Never enter passwords, OTPs, card numbers, or other secrets. Use handoff.
- Do not buy, pay, delete, post, or submit forms on your own; the harness asks first.
- Read the page before acting. Do not guess URLs or invent element ids.
- Use extract only when you need text that is not already in PAGE.text; then return done.
- If the task is complete, return done. If blocked, return handoff with a reason.

Example: PAGE.text contains "Example Domain" and the task asks for the heading.
Reply: {"action":"done","summary":"The heading is Example Domain."}
"""


class PlannerError(RuntimeError):
    """The local model could not produce a usable plan."""


@dataclass
class BrowseResult:
    summary: str
    steps: int
    stopped: str
    extracts: list[str] = field(default_factory=list)


class ModelPlanner:
    def __init__(
        self,
        gateway_url: str,
        model: str = "local-agent",
        timeout: float = 120.0,
    ) -> None:
        self.base = gateway_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _observation(self, observation: dict) -> dict:
        elements = []
        for element in observation.get("elements", [])[:40]:
            item = {
                key: element.get(key)
                for key in ("id", "tag", "type", "role", "name", "value", "href", "disabled", "sensitive")
                if element.get(key) not in (None, "", False)
            }
            elements.append(item)
        return {
            "url": observation.get("url"),
            "title": observation.get("title"),
            "text": str(observation.get("text") or "")[:2500],
            "elements": elements,
        }

    def plan(
        self,
        task: str,
        observation: dict,
        history: list[str],
        correction: str = "",
    ) -> str:
        page = json.dumps(self._observation(observation), ensure_ascii=False)
        recent = "\n".join(history[-6:]) or "(none)"
        user = f"TASK: {task}\n\nPAGE: {page}\n\nRECENT ACTIONS:\n{recent}\n"
        if correction:
            user += f"\nCorrection: {correction}\n"
        user += "\nReturn the next action as one JSON object."
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = httpx.post(
                f"{self.base}/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 400:
                payload.pop("response_format", None)
                response = httpx.post(
                    f"{self.base}/v1/chat/completions",
                    headers={"Authorization": "Bearer local"},
                    json=payload,
                    timeout=self.timeout,
                )
        except httpx.HTTPError as exc:
            raise PlannerError(f"gateway unreachable: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise PlannerError(f"gateway HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PlannerError("gateway returned a malformed completion") from exc
        if not content.strip():
            raise PlannerError("model returned an empty reply")
        return content


class AuditLog:
    """Append-only local record of every step. Text fills are length-only."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            root = DATA_DIR / "browser" / "runs"
            root.mkdir(parents=True, exist_ok=True)
            try:
                root.chmod(0o700)
            except OSError:
                pass
            path = root / f"{datetime.now():%Y%m%d-%H%M%S}-browse.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.path.touch(mode=0o600, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, kind: str, **data: object) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, **data}
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:
            pass


def _action_record(action: Action) -> dict:
    data = action.as_dict()
    if action.kind == "fill":
        data["text"] = f"<{len(action.text)} chars>"
    return data


class BrowserAgent:
    def __init__(
        self,
        session: BrowserSession,
        planner: ModelPlanner,
        policy: BrowserPolicy,
        max_steps: int = 15,
        headless: bool = False,
        confirm: Callable[[str], bool] | None = None,
        pause: Callable[[str], None] | None = None,
        audit: AuditLog | None = None,
        screenshots_dir: Path | None = None,
    ) -> None:
        self.session = session
        self.planner = planner
        self.policy = policy
        self.max_steps = max(1, max_steps)
        self.headless = headless
        self.confirm = confirm
        self.pause = pause
        self.audit = audit
        self.screenshots_dir = screenshots_dir
        self.extracts: list[str] = []
        self.screenshots: list[str] = []

    def _log(self, kind: str, **data: object) -> None:
        if self.audit is not None:
            self.audit.write(kind, **data)

    def _capture(self, name: str) -> None:
        if self.screenshots_dir is None:
            return
        path = self.screenshots_dir / f"{name}-{time.strftime('%H%M%S')}.png"
        shot = self.session.screenshot(path)
        if shot:
            self.screenshots.append(str(shot))

    def _finish(self, stopped: str, summary: str, steps: int) -> BrowseResult:
        self._capture(stopped)
        return BrowseResult(summary, steps, stopped, self.extracts)

    def run(self, task: str) -> BrowseResult:
        history: list[str] = []
        step = 0
        pauses = 0
        while step < self.max_steps:
            observation = self.session.observe()
            self._log(
                "observe",
                step=step + 1,
                url=observation.get("url"),
                title=observation.get("title"),
                captcha=observation.get("captcha"),
            )
            if observation.get("captcha"):
                if self.headless:
                    return self._finish(
                        "captcha",
                        "A CAPTCHA or bot check appeared; rerun without --headless to solve it manually.",
                        step,
                    )
                if self.pause is None:
                    return self._finish(
                        "captcha",
                        "CAPTCHA detected and no interactive handoff is available.",
                        step,
                    )
                pauses += 1
                if pauses > 5:
                    return self._finish(
                        "captcha", "Still blocked by a CAPTCHA after several handoffs.", step
                    )
                self.pause(
                    "CAPTCHA or browser check detected. Solve it in the visible window, "
                    "then come back here."
                )
                continue

            step += 1
            try:
                raw = self.planner.plan(task, observation, history)
                try:
                    action = parse_action(raw)
                except ActionError as exc:
                    raw = self.planner.plan(
                        task,
                        observation,
                        history,
                        correction=(
                            f"Your previous reply was invalid ({exc}). "
                            "Return exactly one JSON object from the allowed actions."
                        ),
                    )
                    action = parse_action(raw)
            except (PlannerError, ActionError) as exc:
                return self._finish("error", f"Planner error: {exc}", step)

            self._log("plan", step=step, action=_action_record(action))
            if action.kind == "done":
                self._log("done", step=step, summary=action.summary)
                return self._finish("done", action.summary, step)
            if action.kind == "handoff":
                if self.headless or self.pause is None:
                    return self._finish("handoff", f"Handoff required: {action.reason}", step)
                self.pause(
                    f"Handoff: {action.reason}\nTake over in the browser window, then return here."
                )
                history.append(f"{step}. handoff: {action.reason}")
                continue

            try:
                result = self.session.perform(action, confirm=self.confirm)
            except SensitiveFieldError as exc:
                if self.headless or self.pause is None:
                    return self._finish("handoff", str(exc), step)
                self.pause(
                    f"{exc}\nType the secret yourself in the browser, then return here."
                )
                history.append(f"{step}. blocked sensitive field")
                continue
            except (BrowserError, PolicyError) as exc:
                self._log("error", step=step, detail=str(exc))
                return self._finish("error", f"Action failed: {exc}", step)

            self._log(
                "result",
                step=step,
                ok=result.get("ok"),
                detail=result.get("detail"),
                cancelled=result.get("cancelled", False),
            )
            if result.get("extract"):
                self.extracts.append(str(result["extract"]))
            if result.get("cancelled"):
                return self._finish("cancelled", "Action cancelled by the user.", step)
            history.append(f"{step}. {action.kind}: {result.get('detail', 'ok')}")

        self._log("limit", steps=step)
        return self._finish(
            "max-steps",
            f"Reached the {self.max_steps}-step limit before finishing.",
            step,
        )
