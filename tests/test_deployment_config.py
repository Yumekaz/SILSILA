from __future__ import annotations

from pathlib import Path


def test_render_blueprint_includes_port_binding_and_persistent_disk():
    render_yaml = Path("render.yaml").read_text(encoding="utf-8")

    assert "runtime: python" in render_yaml
    assert "gunicorn server:server --config gunicorn.conf.py" in render_yaml
    assert "healthCheckPath: /healthz" in render_yaml
    assert "mountPath: /var/data" in render_yaml
    assert "SILSILA_DB_PATH" in render_yaml
    assert "WEB_CONCURRENCY" in render_yaml


def test_gunicorn_config_reads_port_from_environment():
    gunicorn_conf = Path("gunicorn.conf.py").read_text(encoding="utf-8")

    assert "PORT" in gunicorn_conf
    assert "bind =" in gunicorn_conf
    assert "WEB_CONCURRENCY" in gunicorn_conf
    assert "GUNICORN_THREADS" in gunicorn_conf
