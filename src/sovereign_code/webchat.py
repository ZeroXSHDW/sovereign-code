"""A fully local ChatGPT-style web client for the tier gateway.

No CDN, no telemetry, no cloud calls: the page is inline, the server binds
127.0.0.1, and all completions go through the local-only tier gateway.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from .config import LOCAL_AI_ROOT
from .http import client_for
from .tier_gateway import local_only, port_open

DEFAULT_PORT = 4020
DEFAULT_ROUTER = "http://127.0.0.1:4010"
_LAST_SHOT: Path | None = None


def pid_path() -> Path:
    return LOCAL_AI_ROOT / "data" / "run" / "webchat.pid"


# The routes the picker offers, and how they are described. The names come
# from the catalog, so a new route shows up without touching this file.
ROUTE_LABELS = {
    "best": "30B code / GLM reasoning",
    "auto": "latency first",
    "deep": "30B coder",
    "ultra": "27B reasoning",
    "balanced": "9B, 65k",
    "fast": "4B",
}


def model_options() -> str:
    """The model picker, built from the local catalog."""
    from .tier_gateway import catalog_models, installed_models

    entries = {str(entry["id"]): entry for entry in catalog_models(installed_models())}
    rows: list[str] = []
    for name, label in ROUTE_LABELS.items():
        entry = entries.get(name)
        if entry is None:
            continue
        model = str(entry["model"])
        text = f"{label} · {model}" if model and model != name else label
        rows.append(f'    <option value="{name}">{name} — {text}</option>')
    return "\n".join(rows) or '    <option value="best">best</option>'


def page() -> str:
    """The page, with the model picker filled from the catalog."""
    return HTML.replace("<!--MODELS-->", model_options())


def log_path() -> Path:
    return LOCAL_AI_ROOT / "data" / "logs" / "webchat.log"


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ChatGPT Local · Sovereign</title>
<style>
:root{--bg:#0b0d10;--panel:#12161c;--line:#5a6d8a;--text:#e8edf5;--muted:#8b98a8;--accent:#7c9cff;--user:#1c2a44;--ok:#48d597}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.app{display:grid;grid-template-columns:260px 1fr;height:100vh}
aside{background:var(--panel);border-right:1px solid var(--line);padding:18px;display:flex;flex-direction:column;gap:14px}
h1{font-size:16px;margin:0;letter-spacing:.2px}h1 span{color:var(--accent)}
.badge{font-size:12px;color:var(--ok);border:1px solid #234;border-radius:999px;padding:4px 8px;display:inline-flex;gap:6px;align-items:center}
.badge:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ok)}
label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
select,input,textarea,button{font:inherit;color:var(--text);background:#0f141a;border:1px solid var(--line);border-radius:10px;padding:10px}
select,input{width:100%}button{cursor:pointer;background:#182233;border-color:#26344a}button:hover{border-color:var(--accent)}
/* The focus ring was removed, which left keyboard users with no indication
   of where they were. WCAG 2.4.7 wants a visible focus indicator. */
select:focus-visible,input:focus-visible,textarea:focus-visible,button:focus-visible,.skill:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ghost{background:transparent}.skills{flex:1;overflow:auto;display:flex;flex-direction:column;gap:8px;min-height:80px}
.skill{font-size:12px;padding:8px;border:1px solid var(--line);border-radius:8px;cursor:pointer;text-align:left;background:transparent;color:inherit;width:100%}.skill b{display:block;font-size:12px;color:#cfd9e6}.skill small{color:var(--muted)}
main{display:flex;flex-direction:column;min-width:0}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
#chat{flex:1;overflow:auto;padding:24px 20px;display:flex;flex-direction:column;gap:16px}
.msg{max-width:820px;width:100%;margin:0 auto;display:flex;gap:12px}
.avatar{width:30px;height:30px;border-radius:8px;background:#1a2230;display:grid;place-items:center;font-size:12px;color:var(--accent);flex:none}
.bubble{flex:1;white-space:pre-wrap;word-break:break-word;padding:12px 14px;border-radius:12px;background:#10151c;border:1px solid var(--line)}
.user .bubble{background:var(--user)}.meta{font-size:11px;color:var(--muted);margin-bottom:4px}
form{display:flex;gap:10px;padding:16px 20px 20px;border-top:1px solid var(--line);max-width:860px;width:100%;margin:0 auto}
textarea{flex:1;resize:none;min-height:52px;max-height:180px}#send{width:92px;background:var(--accent);color:#08101f;border:0;font-weight:650}
.hint{font-size:11px;color:var(--muted);text-align:center;padding:0 20px 10px}
.visually-hidden{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
code{background:#0a0e13;padding:2px 4px;border-radius:4px}pre{background:#0a0e13;padding:10px;border-radius:8px;overflow:auto}
@media(max-width:760px){.app{grid-template-columns:1fr;grid-template-rows:auto 1fr}
 /* Hiding the sidebar took the model picker, the browser controls and the
    whole skill list with it. The panel now stacks above the chat instead,
    so the page reflows without losing function (WCAG 1.4.10). */
 aside{border-right:0;border-bottom:1px solid var(--line);max-height:45vh;overflow:auto}
}
</style>
</head>
<body>
<div class="app">
<aside>
  <h1>ChatGPT <span>Local</span></h1>
  <div class="badge" id="status">loopback only</div>
  <label for="model">Model</label>
  <select id="model">
<!--MODELS-->
  </select>
  <button class="ghost" id="new">New chat</button>
  <label for="burl">Browser · visible Chromium</label>
  <input id="burl" placeholder="https://example.com">
  <label for="btask">Browser task</label>
  <input id="btask" placeholder="what should it do?">
  <label style="display:flex;gap:6px;align-items:center;font-size:11px"><input type="checkbox" id="blocal" style="width:auto"> allow localhost</label>
  <button class="ghost" id="brun">Run browser task</button>
  <div id="blog" style="font-size:11px;color:var(--muted);white-space:pre-wrap" role="status"></div>
  <img id="bshot" alt="Screenshot of the browser after the last task" style="width:100%;border-radius:8px;display:none">
  <label for="skillq">Skills · all 22k</label>
  <input id="skillq" placeholder="search skills…">
  <div class="skills" id="skills"></div>
</aside>
<main>
  <header><span id="where">127.0.0.1 · no cloud</span><span id="tier" role="status">ready</span></header>
  <div id="chat" role="log" aria-live="polite" aria-relevant="additions text"></div>
  <div class="hint">Enter sends · Shift+Enter newline · everything stays on this Mac</div>
  <form id="form"><label for="input" class="visually-hidden">Message</label><textarea id="input" placeholder="Ask anything, or paste code…" autofocus></textarea><button id="send">Send</button></form>
</main>
</div>
<script>
const chat=document.getElementById('chat'),input=document.getElementById('input'),form=document.getElementById('form');
const model=document.getElementById('model'),status=document.getElementById('status'),tier=document.getElementById('tier');
let messages=JSON.parse(localStorage.getItem('sovereign-chat')||'[]');let busy=false;
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function md(s){let h=esc(s);h=h.replace(/```([\s\S]*?)```/g,(_,c)=>'<pre>'+c+'</pre>');h=h.replace(/`([^`]+)`/g,'<code>$1</code>');return h}
function render(){chat.innerHTML='';for(const m of messages){const d=document.createElement('div');d.className='msg '+m.role;d.innerHTML='<div class="avatar">'+(m.role==='user'?'you':'AI')+'</div><div><div class="meta">'+(m.role==='user'?'You':'Local model')+'</div><div class="bubble">'+md(m.content||'')+'</div></div>';chat.appendChild(d)}chat.scrollTop=chat.scrollHeight}
function save(){localStorage.setItem('sovereign-chat',JSON.stringify(messages))}
function add(role,content){messages.push({role,content});save();render()}
async function send(){if(busy)return;const text=input.value.trim();if(!text)return;input.value='';add('user',text);busy=true;tier.textContent='thinking…';const assistant={role:'assistant',content:''};messages.push(assistant);render();
try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model.value,messages:messages.slice(0,-1)})});
if(!r.ok){throw new Error(await r.text())}
const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});const lines=buf.split('\n');buf=lines.pop()||'';for(const line of lines){if(!line.startsWith('data: '))continue;const raw=line.slice(6).trim();if(raw==='[DONE]')continue;try{const j=JSON.parse(raw);const d=j.choices?.[0]?.delta||{};if(d.content){assistant.content+=d.content;render()}if(j.model)tier.textContent=j.model}catch(e){}}}
}catch(e){assistant.content+='\n\n[error] '+e.message}finally{busy=false;save();render();tier.textContent='ready'}}
form.addEventListener('submit',e=>{e.preventDefault();send()});input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
document.getElementById('new').onclick=()=>{if(busy)return;messages=[];save();render()};
model.onchange=()=>save();
async function browse(){
  const url=document.getElementById('burl').value.trim();const task=document.getElementById('btask').value.trim();
  if(!url||!task){document.getElementById('blog').textContent='URL and task required';return}
  const log=document.getElementById('blog');log.textContent='starting…';
  try{const r=await fetch('/api/browse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,task,allow_local:document.getElementById('blocal').checked,max_steps:10})});
    const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let lines=buf.split('\n');buf=lines.pop()||'';for(const line of lines){if(!line.startsWith('data: '))continue;try{const d=JSON.parse(line.slice(6));if(d.type==='start')log.textContent='browser opened…';if(d.type==='step')log.textContent='step '+d.step+': '+d.action;if(d.type==='done'){log.textContent=d.summary;if(d.screenshot){const img=document.getElementById('bshot');img.src='/api/last-shot?t='+Date.now();img.style.display='block'}}if(d.type==='error')log.textContent='error: '+d.message}catch(e){}}}
  }catch(e){log.textContent='error: '+e.message}
}
document.getElementById('brun').onclick=browse;
async function loadSkills(q){const r=await fetch('/api/skills?q='+encodeURIComponent(q));const rows=await r.json();const box=document.getElementById('skills');box.innerHTML='';for(const s of rows){const el=document.createElement('button');el.type='button';el.className='skill';el.innerHTML='<b>'+esc(s.name)+'</b><small>'+esc((s.description||'').slice(0,90))+'</small>';el.onclick=async()=>{try{const r=await fetch('/api/skill?name='+encodeURIComponent(s.name));const d=await r.json();input.value='Use this skill:\n\n'+(d.body||'');}catch(e){input.value='Use the skill `'+s.name+'`:\n'}input.focus()};box.appendChild(el)}}
document.getElementById('skillq').addEventListener('input',e=>loadSkills(e.target.value));
fetch('/api/health').then(r=>r.json()).then(h=>{status.textContent=h.local_only?'local-only':'cloud allowed';status.style.color=h.local_only?'var(--ok)':'#e0b45c'}).catch(()=>{status.textContent='offline';status.style.color='#e06c6c'});
render();
</script>
</body></html>
"""


def _json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "SovereignChat/1.0"
    router = DEFAULT_ROUTER
    port = DEFAULT_PORT

    def log_message(self, *_args: object) -> None:
        return

    def _host_is_local(self) -> bool:
        """True when the request was addressed to this server by name.

        The Host header is what stops DNS rebinding: an attacker's domain
        that resolves to 127.0.0.1 still arrives here with ``Host:
        attacker.example``, and the browser then treats the reply as
        same-origin with the attacker's page.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            # A request with no Host header is not something a browser sends.
            return False
        name = host.rsplit(":", 1)[0] if ":" in host else host
        name = name.strip("[]")
        return name in {"127.0.0.1", "localhost", "::1"}

    def _origin_is_local(self) -> bool:
        """True when the request carries no cross-origin ``Origin``."""
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            # Same-origin fetches from the bundled page send no Origin.
            return True
        name = origin.split("//", 1)[-1].split("/", 1)[0]
        host = name.rsplit(":", 1)[0] if ":" in name else name
        return host.strip("[]") in {"127.0.0.1", "localhost", "::1"}

    def _reject_cross_origin(self) -> bool:
        """Refuse a request that did not come from this page.

        Returns True when the request was rejected and the caller should
        stop.
        """
        if self._host_is_local() and self._origin_is_local():
            return False
        _json(self, 403, {"error": "cross-origin requests are not allowed"})
        return True

    def do_GET(self) -> None:
        if self._reject_cross_origin():
            return
        path = urlsplit(self.path)
        if path.path == "/":
            body = page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/api/health":
            _json(
                self,
                200,
                {
                    "ok": port_open("127.0.0.1", 4010),
                    "local_only": local_only(),
                    "router": self.router,
                },
            )
            return
        if path.path == "/api/last-shot":
            if _LAST_SHOT is None or not _LAST_SHOT.is_file():
                _json(self, 404, {"error": "no screenshot"})
                return
            data = _LAST_SHOT.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path.path == "/api/skill":
            from .skills_install import get_skill

            name = (parse_qs(path.query).get("name") or [""])[0]
            skill = get_skill(name)
            if skill is None:
                _json(self, 404, {"error": "unknown skill"})
            else:
                _json(self, 200, {"name": skill.name, "body": skill.body[:20000]})
            return
        if path.path == "/api/skills":
            from .skills import search_skills

            query = (parse_qs(path.query).get("q") or [""])[0]
            rows = search_skills(query, limit=12) if query.strip() else []
            _json(self, 200, [{"name": n, "description": d} for n, d in rows])
            return
        _json(self, 404, {"error": "not found"})

    def _browse(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            _json(self, 400, {"error": "invalid JSON"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def event(data: dict) -> None:
            try:
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        event({"type": "start"})
        session = None
        try:
            from .browser.actions import BrowserPolicy, check_url
            from .browser.agent import AuditLog, BrowserAgent, ModelPlanner
            from .browser.executor import BrowserSession
            from .config import LOCAL_AI_ROOT

            policy = BrowserPolicy(allow_local=bool(payload.get("allow_local")))
            url = check_url(str(payload.get("url") or ""), policy)
            task = str(payload.get("task") or "").strip()
            if not task:
                raise ValueError("task is required")
            session = BrowserSession(
                profile_dir=LOCAL_AI_ROOT / "data" / "browser" / "profile",
                policy=policy,
                headless=False,
                timeout_ms=15000,
            )
            session.start(url)
            planner = ModelPlanner(self.router, model="balanced")
            agent = BrowserAgent(
                session,
                planner,
                policy,
                max_steps=max(1, min(int(payload.get("max_steps") or 10), 20)),
                headless=False,
                confirm=lambda _message: False,
                audit=AuditLog(),
                screenshots_dir=LOCAL_AI_ROOT / "data" / "browser" / "screenshots",
            )
            result = agent.run(task)
            global _LAST_SHOT
            if agent.screenshots:
                _LAST_SHOT = Path(agent.screenshots[-1])
            event(
                {
                    "type": "done",
                    "summary": result.summary,
                    "steps": result.steps,
                    "stopped": result.stopped,
                    "screenshot": agent.screenshots[-1] if agent.screenshots else "",
                }
            )
        except Exception as exc:
            event({"type": "error", "message": str(exc)[:400]})
        finally:
            if session is not None:
                session.close()

    def do_POST(self) -> None:
        if self._reject_cross_origin():
            return
        if urlsplit(self.path).path == "/api/browse":
            self._browse()
            return
        if urlsplit(self.path).path != "/api/chat":
            _json(self, 404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            _json(self, 400, {"error": "invalid JSON"})
            return
        request = {
            "model": str(payload.get("model") or "best"),
            "messages": payload.get("messages") or [],
            "stream": True,
            "max_tokens": int(payload.get("max_tokens") or 4096),
        }
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            with client_for(timeout=600, connect=5) as client:
                with client.stream(
                    "POST",
                    f"{self.router}/v1/chat/completions",
                    json=request,
                ) as response:
                    if response.status_code >= 400:
                        error = response.read().decode(errors="replace")
                        self.wfile.write(f"data: {json.dumps({'error': error})}\n\n".encode())
                        return
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
                        self.wfile.flush()
        except (httpx.HTTPError, BrokenPipeError, ConnectionResetError) as exc:
            try:
                self.wfile.write(f"data: {json.dumps({'error': str(exc)})}\n\n".encode())
            except (BrokenPipeError, ConnectionResetError):
                pass


def serve(port: int = DEFAULT_PORT, router: str = DEFAULT_ROUTER) -> None:
    if port_open("127.0.0.1", port):
        # Another instance owns the port. Exiting cleanly keeps launchd from
        # restarting this one into a fight with the server that is up.
        print(f"ChatGPT Local already serving on {port}", flush=True)
        return
    pid_path().parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    pid_path().write_text(str(os.getpid()), encoding="utf-8")
    Handler.router = router
    Handler.port = int(port)
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    print(f"ChatGPT Local · http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def ensure_running(port: int = DEFAULT_PORT, router: str = DEFAULT_ROUTER) -> bool:
    if port_open("127.0.0.1", port):
        return True
    log_path().parent.mkdir(parents=True, exist_ok=True)
    with log_path().open("ab") as log:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sovereign_code",
                "chat-web",
                "--serve",
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "SOVEREIGN_ROUTER_URL": router},
        )
    for _ in range(30):
        if port_open("127.0.0.1", port):
            return True
        time.sleep(0.2)
    return False


def stop(port: int = DEFAULT_PORT) -> bool:
    try:
        pid = int(pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(20):
        if not port_open("127.0.0.1", port):
            try:
                pid_path().unlink()
            except OSError:
                pass
            return True
        time.sleep(0.1)
    return False


def open_browser(port: int = DEFAULT_PORT) -> None:
    webbrowser.open(f"http://127.0.0.1:{port}")


def install_app(port: int = DEFAULT_PORT) -> Path:
    """Create ~/Applications/ChatGPT Local.app that starts the server and opens it."""
    from .config import PROJECT_ROOT

    app = Path.home() / "Applications" / "ChatGPT Local.app"
    app.parent.mkdir(parents=True, exist_ok=True)
    script = f"""on run
  do shell script "cd {PROJECT_ROOT} && {sys.executable} -m sovereign_code chat-web --start --port {int(port)}"
  open location "http://127.0.0.1:{int(port)}"
end run"""
    subprocess.run(
        ["osacompile", "-o", str(app), "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return app
