"""
Open Charvis - Local web server
==============================
Serves the 3D interface and a JSON API, using only ``http.server`` so there
is nothing to install.

Safety properties, matching the agent's own rules:

* binds to ``127.0.0.1`` by default, so nothing on your network can reach it
* every file path it will serve is resolved and jailed before it is opened
* POST bodies are size-capped
* there is no debugger and no interactive console, ever

Run it with ``charvis ui``.
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import PATHS, ensure_dirs, get_config
from .events import BUS
from .logger import log_info, log_warn
from .security import get_security
from .tools import list_tools, run as run_tool

SEC = get_security()
MAX_BODY = 512 * 1024
# Attachments are files to read and summarise, not programs to run.
MAX_UPLOAD = 24 * 1024 * 1024

UPLOAD_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".cs",
    ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat", ".sql", ".log",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",
}

# Directories this server may read files from.
UI_ROOTS = [Path(__file__).resolve().parent.parent / "ui", PATHS["exports"]]


def _ui_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "ui"


class CharvisHandler(BaseHTTPRequestHandler):
    server_version = "OpenCharvis"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """
        Swallow client disconnects quietly.

        A browser that navigates away mid-response aborts the socket, which
        socketserver reports as a full traceback. That is normal on the web,
        and printing a stack trace for it makes the agent look broken.
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True
        except OSError as exc:
            if getattr(exc, "winerror", None) in (10053, 10054, 10064):
                self.close_connection = True
                return
            raise

    # -- plumbing -------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        """Quieter than the default, and never logs request bodies."""
        log_info(f"http {self.address_string()} {fmt % args}", "server")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith(("text/", "application/javascript", "application/json")):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return {}
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}

    def _upload(self) -> None:
        """
        Take an attached file and put it somewhere the agent can read.

        The client sends the bytes as the raw body and the filename in a
        header. The name is stripped down to its stem plus a known-good
        extension before anything touches the filesystem - a browser is
        not a trusted source of path components, and the upload folder is
        the one place a crafted name could escape from.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            self._send_json({"ok": False, "error": "empty upload"}, 400)
            return
        if length > MAX_UPLOAD:
            self._send_json(
                {"ok": False, "error": f"file is larger than {MAX_UPLOAD // (1024 * 1024)} MB"},
                413,
            )
            return

        raw_name = self.headers.get("X-Filename", "")
        try:
            data = self.rfile.read(length)
        except OSError:
            self._send_json({"ok": False, "error": "could not read the upload"}, 400)
            return

        folder = PATHS["exports"] / "uploads"
        folder.mkdir(parents=True, exist_ok=True)

        # Keep only the stem; never trust the extension or the directories.
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw_name).stem)[:60].strip("._-")
        suffix = Path(raw_name).suffix.lower()
        if suffix not in UPLOAD_SUFFIXES:
            suffix = ""
        stamp = int(time.time() * 1000)
        target = folder / f"{stem or 'file'}-{stamp}{suffix}"

        try:
            target.write_bytes(data)
        except OSError as exc:
            self._send_json({"ok": False, "error": f"could not save the file: {exc}"}, 500)
            return

        log_info(f"upload saved {target.name} ({len(data)} bytes)", "server")
        self._send_json({
            "ok": True,
            "path": str(target),
            "name": target.name,
            "size": len(data),
        })

    # -- routing --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - required name
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if route == "/" or route == "/index.html":
            self._send_file(_ui_dir() / "index.html")
            return
        if route.startswith("/ui/"):
            self._serve_ui(route[4:])
            return
        if route == "/api/status":
            self._send_json(self._api_status())
            return
        if route == "/api/tools":
            self._send_json({"ok": True, "count": len(list_tools()), "tools": list_tools()})
            return
        if route == "/api/memory":
            self._send_json(self._api_memory(query))
            return
        if route == "/api/security":
            self._send_json({"ok": True, **SEC.status()})
            return
        if route == "/api/skills":
            from .skills import get_registry

            self._send_json({"ok": True, **get_registry().stats(),
                             "skills": get_registry().listing()})
            return
        if route == "/api/vault":
            from .vault import get_vault

            self._send_json({"ok": True, **get_vault().health(),
                             "secrets": get_vault().listing()})
            return
        if route == "/api/events":
            events = [
                {"name": e.name, "source": e.source, "age": round(e.age(), 2),
                 "payload": _safe_payload(e.payload)}
                for e in BUS.recent(limit=30)
            ]
            self._send_json({"ok": True, "events": events})
            return
        if route == "/api/nlu":
            from .nlu import get_nlu

            self._send_json({"ok": True, **get_nlu().stats_report()})
            return
        if route == "/api/mind":
            from .mind import get_mind

            mind = get_mind()
            query_text = query.get("explain", "")
            self._send_json({
                "ok": True,
                **mind.status(),
                "explanation": mind.explain(query_text) if query_text else None,
            })
            return
        if route == "/api/media":
            self._serve_media(query.get("path", ""))
            return
        if route == "/api/profile":
            from .user import get_profile

            self._send_json({"ok": True, "profile": get_profile().public()})
            return
        if route == "/api/history":
            from .user import get_history

            history = get_history()
            session = query.get("session", "")
            if session:
                self._send_json({
                    "ok": True,
                    "session": session,
                    "messages": history.messages(session, limit=300),
                })
            else:
                self._send_json({
                    "ok": True,
                    "sessions": history.sessions(),
                    "stats": history.stats(),
                })
            return
        if route == "/api/settings":
            from .user import get_settings

            try:
                self._send_json({"ok": True, "settings": get_settings().describe()})
            except KeyError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 404)
            return
        if route == "/api/capabilities":
            from .config import capability_report

            self._send_json({"ok": True, "report": capability_report()})
            return
        self._send_json({"error": "no such route", "path": route}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"

        if route == "/api/upload":
            # Must run before _read_json: the body here is raw file bytes,
            # and _read_json would consume them and then wait for more.
            self._upload()
            return

        payload = self._read_json()

        if route == "/api/chat/think":
            from .brain import get_brain

            enabled = bool(payload.get("enabled"))
            state = get_brain().set_think_mode(enabled)
            self._send_json({"ok": True, "think_mode": state})
            return

        if route == "/api/chat/stream":
            text = str(payload.get("text", "")).strip()
            if not text:
                self._send_json({"ok": False, "error": "empty message"}, 400)
                return
            self._stream_chat(text, payload.get("session", ""))
            return

        if route == "/api/chat":
            text = str(payload.get("text", "")).strip()
            if not text:
                self._send_json({"ok": False, "error": "empty message"}, 400)
                return
            self._send_json(self._api_chat(text, payload.get("source", "web")))
            return

        if route == "/api/think":
            goal = str(payload.get("goal", "")).strip()
            if not goal:
                self._send_json({"ok": False, "error": "empty goal"}, 400)
                return
            from .brain import get_brain

            reply = get_brain().think(goal, source="web")
            self._send_json({"ok": True, **reply.to_dict()})
            return

        if route == "/api/tool":
            name = str(payload.get("name", ""))
            args = payload.get("args") or {}
            if not name:
                self._send_json({"ok": False, "error": "no tool name"}, 400)
                return
            result = run_tool(name, **args)
            self._send_json({"ok": result.ok, **result.to_dict()})
            return

        if route == "/api/memory":
            from .tools import knowledge_tools

            text = str(payload.get("text", "")).strip()
            if not text:
                self._send_json({"ok": False, "error": "nothing to remember"}, 400)
                return
            self._send_json(
                knowledge_tools.memory_remember(
                    text, kind=payload.get("kind", "fact"),
                    tags=payload.get("tags", ""), importance=float(payload.get("importance", 0.6)),
                )
            )
            return

        if route == "/api/posture":
            changed = SEC.apply_posture(str(payload.get("posture", "")))
            self._send_json({"ok": changed, "posture": SEC.cfg.posture})
            return

        if route == "/api/secret":
            from .vault import get_vault

            key = str(payload.get("key", "")).strip().lower()
            value = str(payload.get("value", ""))
            if not key or not value:
                self._send_json({"ok": False, "error": "key and value required"}, 400)
                return
            get_vault().set(key, value, note=str(payload.get("note", "")))
            SEC.audit.record("vault.set", "allow", f"secret '{key}' set via web ui", 0.5)
            self._send_json({"ok": True, "key": key})
            return

        if route == "/api/skills/reload":
            from .skills import get_registry

            self._send_json({"ok": True, **get_registry().load(verbose=False)})
            return

        if route == "/api/skill":
            from .skills import get_registry

            registry = get_registry()
            action = str(payload.get("action", ""))
            if action == "enable":
                self._send_json(registry.enable(str(payload.get("name", ""))))
            elif action == "disable":
                self._send_json(registry.disable(str(payload.get("name", ""))))
            elif action == "run":
                self._send_json(registry.call(
                    str(payload.get("name", "")), **(payload.get("params") or {})
                ).to_dict())
            else:
                self._send_json({"ok": False, "error": "action must be enable/disable/run"})
            return

        if route == "/api/profile":
            from .user import get_profile

            profile = get_profile()
            action = str(payload.get("action", ""))
            if action == "login":
                ok = profile.check_passphrase(str(payload.get("passphrase", "")))
                body = {"ok": ok, "profile": profile.public()}
                if not ok:
                    body["error"] = "wrong passphrase"
                self._send_json(body)
                return
            if action == "setpass":
                ok = profile.set_passphrase(str(payload.get("passphrase", "")))
                self._send_json({"ok": ok, "profile": profile.public(),
                                 "error": None if ok else "passphrase too short"})
                return
            if action == "logout":
                profile.clear_passphrase()
                self._send_json({"ok": True, "profile": profile.public()})
                return
            self._send_json({"ok": True, "profile": profile.set(
                name=payload.get("name"),
                title=payload.get("title"),
                accent=payload.get("accent"),
                voice=payload.get("voice"),
                voice_rate=payload.get("voice_rate"),
            )})
            return

        if route == "/api/history":
            from .user import get_history

            history = get_history()
            action = str(payload.get("action", ""))
            if action == "clear":
                self._send_json({"ok": True,
                                 "removed": history.clear(payload.get("session") or None),
                                 "stats": history.stats()})
                return
            if action == "export":
                self._send_json({"ok": True, "path": str(history.export())})
                return
            self._send_json({"ok": False, "error": "action must be clear or export"})
            return

        if route == "/api/settings":
            from .user import get_settings

            settings = get_settings()
            try:
                changed = {
                    key: settings.set(key, value)
                    for key, value in (payload.get("values") or {}).items()
                }
                if payload.get("save"):
                    settings.save()
                self._send_json({"ok": True, "changed": changed,
                                 "settings": settings.describe()})
            except (KeyError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return

        if route == "/api/mind":
            action = str(payload.get("action", ""))
            from .mind import get_mind

            mind = get_mind()
            if action == "explain":
                self._send_json({"ok": True, **mind.explain(str(payload.get("text", "")))})
            elif action == "reset":
                mind.reset()
                self._send_json({"ok": True, **mind.status()})
            elif action == "correct":
                self._send_json(mind.correct(
                    str(payload.get("text", "")),
                    str(payload.get("wrong", "")),
                    str(payload.get("right", "")),
                ))
            else:
                self._send_json(
                    {"ok": False, "error": "action must be explain / reset / correct"}
                )
            return

        if route == "/api/improve":
            from .self_improve import improve_now

            self._send_json({"ok": True, "report": improve_now(full=bool(payload.get("full")))})
            return

        if route == "/api/image":
            from .tools import media_tools

            self._send_json(
                media_tools.media_image(
                    str(payload.get("prompt", "charvis")),
                    style=str(payload.get("style", "plasma")),
                    width=int(payload.get("width", 512)),
                    height=int(payload.get("height", 512)),
                )
            )
            return

        self._send_json({"error": "no such route", "path": route}, 404)

    # -- handlers -------------------------------------------------------
    def _api_status(self) -> Dict[str, Any]:
        from .brain import get_brain
        from .vault import get_vault

        try:
            brain = get_brain().status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "agent": brain,
            "memory": _memory_stats(),
            "security": {"posture": SEC.cfg.posture, "advice": SEC.advise()},
            "vault": get_vault().health(),
            "tools": len(list_tools()),
            "time": time.time(),
        }

    def _api_chat(self, text: str, source: str) -> Dict[str, Any]:
        from .brain import get_brain

        reply = get_brain().think(text, source=source)
        return {"ok": True, **reply.to_dict()}

    # -- streaming -----------------------------------------------------
    def _stream_chat(self, text: str, session: str = "") -> None:
        """
        Server-Sent Events: the answer arrives word by word.

        The response is **chunked** on purpose. Without a Content-Length and
        without ``Transfer-Encoding: chunked`` an HTTP/1.1 client has no way
        to know where the body ends, so the browser waits forever for a reply
        that has in fact already arrived - which looks exactly like the
        streaming silently failing.
        """
        import json as _json

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        alive = [True]

        def emit(event: Dict[str, Any]) -> bool:
            if not alive[0]:
                return False
            payload = f"data: {_json.dumps(event, default=str)}\n\n".encode("utf-8")
            try:
                self.wfile.write(f"{len(payload):X}\r\n".encode("ascii"))
                self.wfile.write(payload)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError,
                    ConnectionAbortedError, OSError):
                alive[0] = False
                return False

        try:
            from .brain import get_brain

            brain = get_brain()
            if session:
                brain.session = str(session)
            for event in brain.stream_think(text, source="web"):
                if not emit(event):
                    return          # browser went away, stop working
        except Exception as exc:
            emit({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")   # end-of-stream marker
                self.wfile.flush()
            except Exception:
                pass

    def _api_memory(self, query: Dict[str, str]) -> Dict[str, Any]:
        stats = _memory_stats()
        q = query.get("q", "").strip()
        if not q:
            return {"ok": True, "stats": stats}
        from .memory import get_memory

        results = get_memory().search(q, limit=10)
        return {
            "ok": True,
            "stats": stats,
            "results": [
                {"text": r.memory.text, "kind": r.memory.kind, "score": round(r.score, 3),
                 "importance": round(r.memory.importance, 2), "tags": r.memory.tags}
                for r in results
            ],
        }

    def _serve_ui(self, relative: str) -> None:
        """Serve a file from the ui/ folder, resolving relative names inside it."""
        root = _ui_dir()
        candidate = (root / relative.lstrip("/\\")).resolve()
        safe = SEC.safe_target(str(candidate), UI_ROOTS)
        if not safe or not Path(safe).is_file():
            self._send_json({"error": "not found"}, 404)
            return
        self._send_file(Path(safe))

    def _serve_media(self, requested: str) -> None:
        if not requested:
            self._send_json({"error": "no path"}, 400)
            return
        safe = SEC.safe_target(requested, [PATHS["exports"], Path.home()])
        if not safe or not Path(safe).is_file():
            self._send_json({"error": "not found or outside allowed areas"}, 404)
            return
        self._send_file(Path(safe))


def _memory_stats() -> Dict[str, Any]:
    try:
        from .memory import get_memory

        return get_memory().stats()
    except Exception as exc:
        return {"error": str(exc)}


def _safe_payload(payload: Any) -> Any:
    """Trim event payloads so the UI never receives a huge blob."""
    try:
        text = json.dumps(payload, default=str)
        return json.loads(text) if len(text) < 900 else {"summary": text[:900] + "..."}
    except (TypeError, ValueError):
        return str(payload)[:400]


# --------------------------------------------------------------------------
# Server control
# --------------------------------------------------------------------------


class CharvisServer:
    """Threaded HTTP server bound to loopback."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        ensure_dirs()

    def start(self, background: bool = True) -> str:
        if self._httpd is not None:
            return self.url
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), CharvisHandler)
        except OSError as exc:
            raise RuntimeError(
                f"cannot bind {self.host}:{self.port} - {exc}. "
                "Another program may be using that port."
            ) from exc
        self._httpd.daemon_threads = True

        if background:
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
        else:
            # Must actually start serving, otherwise the socket is bound and
            # listening but nothing ever accepts: clients connect and then
            # hang until they time out.
            print(f"  serving on {self.url} (loopback only)", flush=True)
            self._httpd.serve_forever()

        log_info(f"interface on {self.url}", "server")
        return self.url

    def serve_forever(self) -> None:
        self.start(background=False)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            log_info("interface stopped", "server")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Blocking start, used by ``charvis ui``."""
    server = CharvisServer(host, port)
    url = server.start(background=False)
    print(f"\n  Open Charvis interface -> {url}\n  Press Ctrl+C to close.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  closing the interface")
        server.stop()