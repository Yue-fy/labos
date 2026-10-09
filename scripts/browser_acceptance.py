"""Optional real-browser acceptance; install playwright separately in the development env."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from labos.cli import provision
from labos.config import CentralConfig, load_config

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / "runtime" / ("browser-" + str(int(time.time())))
directory.mkdir(parents=True)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
url = f"http://127.0.0.1:{port}"
paths = provision(directory / "config", url, port=port)
config = load_config(paths["central"], CentralConfig)
processes, handles = [], []
environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
try:
    for name in ("central", "pc-a", "pc-b"):
        handle = (directory / f"{name}.log").open("w")
        handles.append(handle)
        processes.append(subprocess.Popen([sys.executable, "-m", "labos",
                                            "central" if name == "central" else "agent",
                                            "--config", str(paths[name])],
                                           env=environment, stdout=handle, stderr=subprocess.STDOUT))
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {config.admin_token}"},
                      timeout=3, trust_env=False) as client:
        deadline = time.monotonic() + 30
        while True:
            try:
                result = client.get("/api/status")
                if result.status_code == 200 and all(i["online"] for i in result.json()["instruments"]):
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("browser test services failed to start")
            time.sleep(0.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator("#token").fill(config.admin_token)
            page.locator("#connect").click()
            page.wait_for_function("document.getElementById('setup_id').options.length > 0")
            page.locator("#angle_stop_deg").fill("20")
            page.locator("#exposure_ms").fill("1")
            page.locator("#prepare").click()
            page.wait_for_function("!document.getElementById('start').disabled")
            page.locator("#start").click()
            page.wait_for_function("document.getElementById('runs').textContent.includes('COMPLETED')",
                                   timeout=30000)
            with page.expect_download() as download_event:
                page.get_by_role("button", name="下载 HDF5").first.click()
            download = download_event.value
            download.save_as(directory / download.suggested_filename)
            assert not errors, errors
            page.locator("#token").fill("")
            page.screenshot(path=str(directory / "dashboard.png"), full_page=True)
            page.locator("#logout").click()
            assert page.locator("#token").input_value() == ""
            browser.close()
            result = {"status": "PASS", "steps": ["login", "preflight", "start", "complete",
                                                      "HDF5 download", "logout"],
                      "javascript_errors": errors, "screenshot": str(directory / "dashboard.png")}
            (directory / "browser-acceptance.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
finally:
    for process in reversed(processes):
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for handle in handles:
        handle.close()
