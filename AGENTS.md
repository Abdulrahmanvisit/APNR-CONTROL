# AGENTS.md

This file defines commands and guidelines for contributors and agents working on the APNR Control Center.

## Commands

### Install Dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Run Application Locally

```powershell
.\venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000/login — auto-provisioned admin: `admin` / `ChangeMe123456`

### Run Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

### Provision Additional Users

```powershell
.\venv\Scripts\python.exe manage_users.py <username> --role Admin|Supervisor|Operator|Auditor
```

### Type Checking (if available)

```powershell
.\venv\Scripts\python.exe -m mypy app.py main.py --ignore-missing-imports
```

### Linting

The project uses Python standard formatting. Run `py_compile` to check syntax:

```powershell
.\venv\Scripts\python.exe -m py_compile app.py main.py
```

## Deployment

- **Render**: Push to `main` branch triggers auto-deploy. PostgreSQL add-on optional — SQLite fallback enables login without external database.
- **Health check**: `https://apnr-control.onrender.com/health`
- **Admin login**: `admin` / `ChangeMe123456` (reset after first login)
- **Render provisioning helper**: `python render_provision.py` (run via Render Shell)
