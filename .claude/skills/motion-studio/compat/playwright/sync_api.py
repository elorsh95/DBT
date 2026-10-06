"""Minimal stand-in for playwright.sync_api, standard library only.

Covers exactly the subset motion-studio's render.py uses, by driving an
already-installed Chromium over the DevTools protocol (--remote-debugging-pipe).
For environments where `pip install playwright` is blocked but a Chromium
binary is present. Put the parent `compat/` folder on PYTHONPATH to use it.

Browser lookup: $CHROMIUM_PATH, then $PLAYWRIGHT_BROWSERS_PATH/chromium-*/chrome-linux/chrome.
"""
import glob
import json
import os
import re
import subprocess
from pathlib import Path


class Error(Exception):
    pass


def _find_chromium():
    if os.environ.get("CHROMIUM_PATH"):
        return os.environ["CHROMIUM_PATH"]
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    hits = sorted(glob.glob(os.path.join(root, "chromium-*/chrome-linux/chrome")))
    if hits:
        return hits[-1]
    raise Error("no Chromium found: set CHROMIUM_PATH")


class _Pipe:
    def __init__(self, args):
        to_r, to_w = os.pipe()      # we write -> browser reads on fd 3
        from_r, from_w = os.pipe()  # browser writes on fd 4 -> we read

        def child():
            # move both ends out of the way first: a pipe may already sit on fd 3 or 4
            a, b = os.dup(to_r), os.dup(from_w)
            os.dup2(a, 3)
            os.dup2(b, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)

        self.proc = subprocess.Popen(args, preexec_fn=child,
                                     close_fds=False, stdout=subprocess.DEVNULL,
                                     stderr=None if os.environ.get("PWSHIM_DEBUG") else subprocess.DEVNULL)
        os.close(to_r)
        os.close(from_w)
        self.w = os.fdopen(to_w, "wb", buffering=0)
        self.r = os.fdopen(from_r, "rb", buffering=0)
        self.buf = b""
        self.next_id = 0
        self.handlers = []          # (session_id, callback(method, params))

    def _read_msg(self):
        while b"\0" not in self.buf:
            chunk = self.r.read(1 << 20)
            if not chunk:
                raise Error("browser closed the connection")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return json.loads(raw)

    def send(self, method, params=None, session=None):
        self.next_id += 1
        mid = self.next_id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.w.write(json.dumps(msg).encode() + b"\0")
        while True:
            m = self._read_msg()
            if m.get("id") == mid:
                if "error" in m:
                    raise Error(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})
            self._dispatch(m)

    def _dispatch(self, m):
        if "method" in m:
            for sid, cb in self.handlers:
                if sid == m.get("sessionId"):
                    cb(m["method"], m.get("params", {}))

    def wait_event(self, session, name):
        got = []
        h = (session, lambda meth, p: got.append(p) if meth == name else None)
        self.handlers.append(h)
        try:
            while not got:
                self._dispatch(self._read_msg())
        finally:
            self.handlers.remove(h)
        return got[0]


class _ConsoleMessage:
    def __init__(self, type_, text):
        self.type, self.text = type_, text


class _CDPSession:
    def __init__(self, page):
        self._page = page

    def send(self, method, params=None):
        return self._page._send(method, params)


class _Context:
    def __init__(self, page):
        self._page = page

    def new_cdp_session(self, page):
        return _CDPSession(page)


_FN = re.compile(r"^\s*(async\s+)?(function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)", re.S)


def _remote_value(o):
    if o.get("type") == "undefined":
        return None
    return o.get("value")


class Page:
    def __init__(self, browser, session, viewport, scale):
        self._b, self._s = browser, session
        self._scale = scale
        self._listeners = {"console": [], "pageerror": []}
        self.context = _Context(self)
        browser._pipe.handlers.append((session, self._on_event))
        self._send("Page.enable")
        self._send("Runtime.enable")
        self.set_viewport_size(viewport)

    def _send(self, method, params=None):
        return self._b._pipe.send(method, params, self._s)

    def _on_event(self, method, p):
        if method == "Runtime.consoleAPICalled":
            kind = {"warn": "warning"}.get(p.get("type"), p.get("type"))
            text = " ".join(str(_remote_value(a) if "value" in a else a.get("description", "")) for a in p.get("args", []))
            for cb in self._listeners["console"]:
                cb(_ConsoleMessage(kind, text))
        elif method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            text = d.get("exception", {}).get("description") or d.get("text", "error")
            for cb in self._listeners["pageerror"]:
                cb(Error(text))

    def on(self, name, cb):
        self._listeners.setdefault(name, []).append(cb)

    def add_init_script(self, script):
        self._send("Page.addScriptToEvaluateOnNewDocument", {"source": script})

    def set_viewport_size(self, vp):
        self._send("Emulation.setDeviceMetricsOverride", {"width": int(vp["width"]), "height": int(vp["height"]),
                                                          # render.py already scales via the screenshot clip; scaling here too would apply it twice
                                                          "deviceScaleFactor": 1, "mobile": False})

    def goto(self, url):
        self._send("Page.navigate", {"url": url})
        self._b._pipe.wait_event(self._s, "Page.loadEventFired")

    def evaluate(self, expression, arg=None):
        if _FN.match(expression):
            expression = f"({expression})({json.dumps(arg) if arg is not None else ''})"
        r = self._send("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                            "returnByValue": True, "userGesture": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise Error(d.get("exception", {}).get("description") or d.get("text", "evaluate failed"))
        return _remote_value(r.get("result", {}))


class Browser:
    def __init__(self, args):
        exe = _find_chromium()
        self._dir = Path(os.environ.get("TMPDIR", "/tmp")) / f"pwshim-{os.getpid()}-{id(self)}"
        cmd = [exe, "--headless=new", "--remote-debugging-pipe", "--no-sandbox", "--no-first-run",
               "--no-default-browser-check", "--disable-gpu-sandbox", "--hide-scrollbars", "--mute-audio",
               f"--user-data-dir={self._dir}", *args, "about:blank"]
        self._pipe = _Pipe(cmd)

    def new_page(self, viewport=None, device_scale_factor=1):
        tid = self._pipe.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self._pipe.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        return Page(self, sid, viewport or {"width": 1280, "height": 720}, device_scale_factor)

    def close(self):
        try:
            self._pipe.send("Browser.close")
        except Error:
            pass
        try:
            self._pipe.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._pipe.proc.kill()
        subprocess.run(["rm", "-rf", str(self._dir)])


class _Chromium:
    def launch(self, args=(), **_):
        return Browser(list(args))


class _Playwright:
    chromium = _Chromium()


class sync_playwright:
    def __enter__(self):
        return _Playwright()

    def __exit__(self, *exc):
        return False
