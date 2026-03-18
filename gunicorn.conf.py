from __future__ import annotations

import os


bind = f"0.0.0.0:{os.getenv('PORT', '8050')}"
workers = max(1, int(os.getenv("WEB_CONCURRENCY", "1")))
threads = max(1, int(os.getenv("GUNICORN_THREADS", "4")))
timeout = max(30, int(os.getenv("GUNICORN_TIMEOUT", "120")))
graceful_timeout = max(15, int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30")))
keepalive = max(2, int(os.getenv("GUNICORN_KEEPALIVE", "30")))
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
