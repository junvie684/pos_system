# POS System

A multi-store point-of-sale web app built with Django and PostgreSQL.

- **Platform admin** (`/platform/`) creates stores and their users.
- **Store users** sign in at `/` to sell, manage products (with images), customers and reports, and print receipts with OR numbers.
- **Old sales** are moved to a separate archive database on a per-store schedule.

The Django project lives in [`pos_system/`](pos_system/).

## Run locally

```powershell
cd pos_system
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Content .env "DJANGO_DEBUG=1" -Encoding ascii   # dev mode, uses SQLite
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
```

## Deploy

See [`pos_system/DEPLOY_WINDOWS.md`](pos_system/DEPLOY_WINDOWS.md) for Windows Server 2022 (IIS + Waitress + PostgreSQL 17).

## Docs

- [`docs/AUDIT_PROMPT.md`](docs/AUDIT_PROMPT.md): the production-readiness audit prompt used to review this project.
