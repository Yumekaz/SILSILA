from __future__ import annotations

from pathlib import Path


def test_render_blueprint_includes_port_binding_and_persistent_disk():
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")
    procfile = Path("Procfile").read_text(encoding="utf-8").strip()
    start_command = "gunicorn server:server --config gunicorn.conf.py"

    assert "runtime: python" in render_yaml
    assert start_command in render_yaml
    assert "healthCheckPath: /healthz" in render_yaml
    assert "mountPath: /var/data" in render_yaml
    assert "PYTHON_VERSION" in render_yaml
    assert "3.12.8" in render_yaml
    assert "SILSILA_DB_PATH" in render_yaml
    assert "WEB_CONCURRENCY" in render_yaml
    assert "maxShutdownDelaySeconds" not in render_yaml
    assert procfile == f"web: {start_command}"


def test_render_free_blueprint_uses_ephemeral_storage_and_free_plan():
    render_yaml = Path("render-free.yaml").read_text(encoding="utf-8")
    start_command = "gunicorn server:server --config gunicorn.conf.py"

    assert "runtime: python" in render_yaml
    assert "plan: free" in render_yaml
    assert start_command in render_yaml
    assert "healthCheckPath: /healthz" in render_yaml
    assert "PYTHON_VERSION" in render_yaml
    assert "3.12.8" in render_yaml
    assert "disk:" not in render_yaml
    assert "mountPath:" not in render_yaml
    assert "SILSILA_DB_PATH" in render_yaml
    assert "/tmp/silsila_ops.db" in render_yaml


def test_gunicorn_config_reads_port_from_environment():
    gunicorn_conf = Path("gunicorn.conf.py").read_text(encoding="utf-8")

    assert "PORT" in gunicorn_conf
    assert "bind =" in gunicorn_conf
    assert "WEB_CONCURRENCY" in gunicorn_conf
    assert "GUNICORN_THREADS" in gunicorn_conf


def test_runtime_version_pin_exists_for_render_builds():
    runtime_txt = Path("runtime.txt")
    python_version = Path(".python-version")

    assert runtime_txt.exists()
    assert runtime_txt.read_text(encoding="utf-8").strip() == "python-3.12.8"
    assert python_version.exists()
    assert python_version.read_text(encoding="utf-8").strip() == "3.12.8"


def test_ci_workflow_tracks_runtime_pin_and_smokes_entrypoint():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "PYTHONPATH: ${{ github.workspace }}" in workflow
    assert "sed 's/^python-//' runtime.txt" in workflow
    assert "cache: pip" in workflow
    assert "import server" in workflow
    assert 'client.get("/healthz")' in workflow
    assert "python -m pytest -q" in workflow
