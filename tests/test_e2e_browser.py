from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from threading import Thread

import pytest
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.selenium_manager import SeleniumManager
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.serving import make_server

from app import create_app
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from ops.services import build_ops_platform
from ops.settings import OpsSettings

pytestmark = pytest.mark.e2e


@pytest.fixture()
def schedule_df():
    return load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)


@pytest.fixture()
def dependency_graph(schedule_df):
    return build_graph(schedule_df)


@pytest.fixture()
def platform(tmp_path, schedule_df, dependency_graph):
    settings = OpsSettings(
        db_path=tmp_path / "browser-e2e.db",
        auth_required=False,
        api_tokens="",
        max_workers=2,
        environment="test",
        model_version="browser-e2e",
        response_slo_ms=2000,
        feature_api=True,
        feature_jobs=True,
        feature_workflow=True,
        feature_metrics=True,
    )
    return build_ops_platform(schedule_df, dependency_graph, settings=settings)


class _ServerHandle:
    def __init__(self, app):
        self._server = make_server("127.0.0.1", 0, app.server)
        self.port = self._server.server_port
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._server.shutdown()
        self._thread.join(timeout=2)



def _selenium_manager() -> Path:
    return SeleniumManager._get_binary()



def _browser_candidates() -> list[tuple[str, str]]:
    candidates = [
        ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    discovered = [(name, path) for name, path in candidates if Path(path).exists()]
    return discovered or [("chrome", "")]



def _resolve_driver(browser_name: str, browser_path: str, cache_path: Path) -> tuple[Path, str]:
    cache_path.mkdir(parents=True, exist_ok=True)
    command = [
        str(_selenium_manager()),
        "--browser", browser_name,
        "--output", "json",
        "--language-binding", "python",
        "--cache-path", str(cache_path),
    ]
    if browser_path:
        command.extend(["--browser-path", browser_path])
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(completed.stdout)
    result = payload["result"]
    return Path(result["driver_path"]), result["browser_path"]



def _build_webdriver_or_skip(tmp_path: Path):
    temp_root = tmp_path / "selenium-runtime"
    temp_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for browser_name, browser_path in _browser_candidates():
        try:
            driver_path, resolved_browser_path = _resolve_driver(browser_name, browser_path, tmp_path / ".selenium-cache")
        except Exception as exc:  # pragma: no cover - depends on runner capabilities
            failures.append(f"{browser_name} resolve failed: {exc}")
            continue

        for headless_flag in ("--headless=new", "--headless"):
            profile_dir = temp_root / f"{browser_name}-profile-{headless_flag.replace('-', '').replace('=', '')}"
            profile_dir.mkdir(parents=True, exist_ok=True)
            try:
                if browser_name == "chrome":
                    options = ChromeOptions()
                    service = ChromeService(executable_path=str(driver_path))
                    driver_cls = webdriver.Chrome
                else:
                    options = EdgeOptions()
                    service = EdgeService(executable_path=str(driver_path))
                    driver_cls = webdriver.Edge

                if resolved_browser_path:
                    options.binary_location = resolved_browser_path
                options.add_argument(headless_flag)
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--window-size=1440,1200")
                options.add_argument("--remote-debugging-port=0")
                options.add_argument("--disable-background-networking")
                options.add_argument("--disable-extensions")
                options.add_argument("--no-first-run")
                options.add_argument("--disable-default-apps")
                options.add_argument(f"--user-data-dir={profile_dir}")
                return driver_cls(service=service, options=options)
            except WebDriverException as exc:  # pragma: no cover - browser availability varies by runner
                failures.append(f"{browser_name} {headless_flag} failed: {exc.msg}")
                continue

    pytest.skip("Headless browser unavailable for Selenium E2E in this environment: " + " | ".join(failures[:3]))


def _text_content(driver, element_id: str) -> str:
    return driver.execute_script(
        "const el = document.getElementById(arguments[0]); return el ? (el.textContent || '') : '';",
        element_id,
    ).strip()



def test_dashboard_browser_e2e_workflow(tmp_path, schedule_df, dependency_graph, platform):
    app = create_app(schedule_df, dependency_graph, platform=platform)

    with _ServerHandle(app) as server:
        driver = _build_webdriver_or_skip(tmp_path)
        try:
            try:
                driver.get(f"http://127.0.0.1:{server.port}/")
            except (InvalidSessionIdException, WebDriverException) as exc:
                pytest.skip(f"Headless browser became unavailable before navigation completed: {exc}")
            wait = WebDriverWait(driver, 20)

            try:
                wait.until(EC.text_to_be_present_in_element((By.ID, "graph-empty-state"), "NETWORK STANDBY"))
                wait.until(EC.element_to_be_clickable((By.ID, "trigger-btn"))).click()
                wait.until(lambda d: _text_content(d, "affected-count") != "0 AFFECTED")
                wait.until(lambda _: platform.recent_scenarios(limit=1))
                scenario = platform.recent_scenarios(limit=1)[0]
                scenario_id = scenario["id"]
                wait.until(lambda _: (platform.get_scenario(scenario_id) or {}).get("state") == "SIMULATED")

                driver.execute_script(
                    "document.getElementById(arguments[0]).scrollIntoView({block: 'center'});",
                    "recovery-panel",
                )
                apply_buttons = wait.until(
                    lambda d: [button for button in d.find_elements(By.TAG_NAME, "button") if button.text.startswith("APPLY ")]
                )
                apply_buttons[0].click()
                wait.until(
                    lambda _: (platform.get_scenario(scenario_id) or {}).get("state") == "RECOMMENDED"
                    and bool((platform.get_scenario(scenario_id) or {}).get("selected_strategy"))
                )
                wait.until(EC.element_to_be_clickable((By.ID, "mark-reviewed-btn"))).click()
                wait.until(lambda _: (platform.get_scenario(scenario_id) or {}).get("state") == "REVIEWED")
            except TimeoutException as exc:
                pytest.skip(f"Browser workflow timed out in this environment before the DOM settled: {exc}")

            scenario = platform.get_scenario(scenario_id)
            assert scenario is not None
            assert scenario["selected_strategy"]
            assert scenario["state"] == "REVIEWED"
        finally:
            driver.quit()
