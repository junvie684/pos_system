"""
Run the POS on Windows with Waitress (gunicorn does not run on Windows).

IIS sits in front of it, handles HTTPS on port 443, and forwards requests here.
Waitress only listens on 127.0.0.1, so nobody can reach it except IIS on this
machine. See DEPLOY_WINDOWS.md.

    python serve_windows.py
"""
import os

from waitress import serve

from pos_system.wsgi import application

serve(
    application,
    listen=os.environ.get('POS_LISTEN', '127.0.0.1:8000'),
    threads=int(os.environ.get('POS_THREADS', '8')),
    # Trust IIS (same machine) to say the browser used HTTPS.
    trusted_proxy='127.0.0.1',
    trusted_proxy_headers={'x-forwarded-proto'},
    clear_untrusted_proxy_headers=True,
)
