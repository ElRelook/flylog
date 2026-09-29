"""Take the README screenshots of the demo pages with a headless Chromium (Edge or Chrome).

Serve the site first (python -m http.server 8000), then:
    pip install websocket-client
    python scripts/screenshots.py

Only the demo data (simulated flights) is shown: a fresh browser profile is used.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

BASE = "http://localhost:8000/"
OUT = Path(__file__).parent.parent / "docs"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google-chrome", "chromium", "microsoft-edge",
]
PORT = 9333

# (file, url, JS condition meaning "ready", JS run before the shot, width, height)
SHOTS = [
    ("capture-vol.png", "?demo=vol",
     "typeof state !== 'undefined' && !!state.data && !!document.querySelector('#piloting dd')",
     "window.scrollTo(0, 0)", 1280, 1500),
    ("capture-carnet.png", "?demo=carnet",
     "typeof lb !== 'undefined' && lb.demo && Object.keys(lb.flights).length >= 12 "
     "&& document.getElementById('lb-progress').hidden",
     "lb.hotLayer && (lb.hotLayer.addTo(lb.map), lb.hotLegend.addTo(lb.map)); window.scrollTo(0, 0)", 1280, 2200),
]


class Tab:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self.n = 0

    def call(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def eval(self, expr: str):
        res = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return res.get("result", {}).get("value")


def main() -> None:
    exe = next((b for b in BROWSERS if Path(b).exists() or shutil.which(b)), None)
    if not exe:
        raise SystemExit("Aucun navigateur Chromium trouvé (Edge ou Chrome).")
    profile = tempfile.mkdtemp(prefix="flylog-shots-")
    proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             f"--remote-allow-origins=http://127.0.0.1:{PORT}",
                             "--hide-scrollbars", "--no-first-run", "about:blank"])
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        tab = Tab(page["webSocketDebuggerUrl"])
        tab.call("Page.enable")
        OUT.mkdir(exist_ok=True)
        for name, query, ready, before, width, height in SHOTS:
            tab.call("Emulation.setDeviceMetricsOverride",
                     width=width, height=height, deviceScaleFactor=1, mobile=False)
            tab.call("Page.navigate", url=BASE + query)
            deadline = time.time() + 90
            while not tab.eval(ready):
                if time.time() > deadline:
                    status = tab.eval("location.href + ' | ' + (document.getElementById('status')?.textContent || '')")
                    raise SystemExit(f"Page jamais prête : {query} ({status})")
                time.sleep(0.5)
            tab.eval(before)
            time.sleep(8)  # map tiles and animations
            data = tab.call("Page.captureScreenshot", format="png")["data"]
            (OUT / name).write_bytes(base64.b64decode(data))
            print(f"  {name} ({width}×{height})")
    finally:
        if shutil.which("taskkill"):  # Windows: also stop the browser's child processes
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
