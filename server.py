"""
server.py
---------
Dedicated WSGI entrypoint for deployment targets such as Gunicorn.
"""

from app import build_runtime_app


app = build_runtime_app()
server = app.server
