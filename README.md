# APNR Control Center

Automatic Plate Number Recognition (APNR) access-control prototype for the Nigeria Police Academy, Wudil, Kano (POLAC) Main Gate.

The application captures a vehicle image, preprocesses it with OpenCV, recognizes plate text with Tesseract OCR, compares the normalized result with a central watchlist, records the decision, and presents a role-specific operations workspace.

## Scope

The current design targets:

- Standard Nigerian vehicle plates, especially Kano State and FCT Abuja formats.
- Daylight operation from 07:00 to 18:00.
- Stationary or slow-moving vehicles below 10 km/h.
- A fixed camera positioned approximately three metres from the inspection point.
- Manual review for unreadable or low-confidence plates.

This prototype does not provide night recognition, facial recognition, unrestricted high-speed tracking, or automatic gate opening.

## Features

- OpenCV image preprocessing and multi-pass Tesseract OCR.
- Explicit decisions: `Allowed`, `Blocked`, `Unauthorized`, and `Unreadable`.
- Admin, Supervisor, Gate Operator, and Auditor RBAC roles.
- Dedicated role workspaces and least-privilege route protection.
- Watchlist create, edit, delete, duplicate detection, and live filtering.
- Entry/Exit event recording and audit-log export.
- Argon2id password hashing for new and migrated credentials.
- Five-attempt account lockout and 15-minute session lifetime.
- Mandatory first-login password reset for newly provisioned accounts.
- Hardware-neutral visual/audible alert events for blocked and unauthorized plates.

## Requirements

- Windows, macOS, or Linux.
- Python 3.10 or newer.
- MySQL Server with an `apnr_db` database.
- Tesseract OCR installed separately.
- A configured camera or image-upload source.

## Installation

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install Tesseract OCR for your operating system. On Windows, the default path is:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

Create a local `.env` file from `.env.example` and set the database connection:

```env
FLASK_SECRET_KEY=replace-with-a-long-random-secret
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=apnr_db
MYSQL_USER=root
MYSQL_PASSWORD=your-local-database-password
```

When deploying on Railway, link a MySQL service to this app. Railway injects
`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`,
and `DATABASE_URL` automatically, pointing at the MySQL service's private
network hostname instead of `localhost`. If `DATABASE_URL` is present, it is
used directly; otherwise the individual `MYSQL_*` variables are used. The
legacy `APNR_DB_*` variable names are still supported as a fallback.

Do not commit `.env`, database passwords, uploaded images, or logs.

## Database Setup

Create the database once in MySQL:

```sql
CREATE DATABASE apnr_db;
```

The application creates and migrates its required tables on the first request. Existing tables are preserved. The schema includes users, watchlist records, detection logs, role-security fields, event direction, alert state, image references, and operator identity.

## Account Provisioning

There is no public account-registration page. Provision accounts from the project terminal:

```powershell
.\venv\Scripts\python.exe manage_users.py academy_admin --role Admin
.\venv\Scripts\python.exe manage_users.py security_supervisor --role Supervisor
.\venv\Scripts\python.exe manage_users.py main_gate_operator --role Operator
.\venv\Scripts\python.exe manage_users.py audit_investigator --role Auditor
```

Each command prompts for the password privately. Passwords must contain at least 12 characters and are stored as Argon2id hashes. New accounts must set a private password on first login.

## Run the Application

Start the local Flask server:

```powershell
.\venv\Scripts\python.exe app.py
```

Open:

```text
http://127.0.0.1:5000/login
```

Role workspaces:

| Role | Workspace |
|---|---|
| Admin | `/admin/dashboard` |
| Supervisor | `/supervisor/dashboard` |
| Gate Operator | `/operator/dashboard` |
| Auditor | `/auditor/dashboard` |

The legacy `/dashboard` route redirects to the correct role workspace.

## Deploy on Railway

This repository is configured for deployment on Railway with zero-config build
support. Railway's Nixpacks buildpack detects the `Procfile`, `requirements.txt`,
`runtime.txt`, and `Aptfile` at the repository root.

### Prerequisites

Add a **MySQL** plugin to your Railway project. Railway injects the connection
details automatically as:

```text
DATABASE_URL=mysql://user:password@host:port/database
MYSQL_HOST  /  MYSQL_USER  /  MYSQL_PASSWORD  /  MYSQL_DATABASE  /  MYSQL_PORT
```

The application resolves these in priority order: `DATABASE_URL` first, then
`MYSQL_*`, then the legacy `APNR_DB_*` variables.

### Build & Runtime

| File            | Purpose                                                     |
|-----------------|--------------------------------------------------------------|
| `Procfile`      | `web: gunicorn app:app --bind 0.0.0.0:$PORT ...`              |
| `requirements.txt` | Python dependencies (`opencv-python-headless` for servers) |
| `runtime.txt`   | Python 3.11                                                    |
| `Aptfile`       | Installs the `tesseract-ocr` system package                    |

### Environment Variables

Set these in the Railway dashboard (Settings → Variables):

| Variable            | Value / Notes                                   |
|---------------------|-------------------------------------------------|
| `FLASK_SECRET_KEY`  | A long random string (generate one)             |
| `FLASK_COOKIE_SECURE` | `1` (HTTPS on Railway)                          |
| `TESSERACT_CMD`     | `/usr/bin/tesseract` (installed via `Aptfile`)  |

The database variables (`DATABASE_URL`, `MYSQL_*`) are injected automatically
when you add the MySQL plugin.

### Deployment Steps

1. Push this repository to GitHub.
2. In Railway, create a new project from your GitHub repository.
3. Add the **MySQL** plugin (Railway → New → Plugin → MySQL).
4. Set the environment variables listed above as secrets.
5. Deploy. Railway builds the image, installs Python + system packages, and
   starts Gunicorn on the allocated `$PORT`.
6. Once the health check passes, provision the first Admin account by running
   `manage_users.py` against the remote database:

```bash
python manage_users.py academy_admin --role Admin
```

The application URL will be supplied by Railway after the first successful
deployment.

### Deploy on Render

The repository includes [render.yaml](render.yaml) for a Render web service. It uses Gunicorn, installs Tesseract OCR during the build, binds Flask to Render's `$PORT`, and keeps secrets in Render environment variables.

Render does not provide the MySQL database required by this application as part of this blueprint. Create or use an external MySQL-compatible database, then connect it with these Render environment variables:

```text
APNR_DB_HOST
APNR_DB_PORT
APNR_DB_NAME
APNR_DB_USER
APNR_DB_PASSWORD
```

Deployment steps:

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Review the service generated from `render.yaml`.
4. Enter the external MySQL connection values as secret environment variables.
5. Deploy the service and wait for the `/login` health check to pass.
6. Provision the first Admin account from a secure local database connection:

```powershell
.\venv\Scripts\python.exe manage_users.py academy_admin --role Admin
```

For a remote Render database, run the same provisioning command only after setting the Render database variables in a secure local environment. Do not put passwords or database credentials in `render.yaml` or Git.

The deployed application URL will be supplied by Render after the first successful deployment.

## Role Permissions

| Capability | Admin | Supervisor | Operator | Auditor |
|---|---:|---:|---:|---:|
| Scan vehicles | Yes | Yes | Yes | Read-only/limited |
| View watchlist | Yes | Yes | Yes | Yes |
| Add/edit/delete watchlist | Yes | Yes | No | No |
| Manage user accounts | Yes | No | No | No |
| Review audit logs | Yes | Yes | Limited | Yes |
| Configure hardware/system | Yes | No | No | No |

Permissions are enforced by backend decorators and the centralized policy in `rbac.py`. Hiding a button is not treated as security.

## OCR Workflow

1. Validate the uploaded image and file type.
2. Resize and convert the image to grayscale.
3. Reduce noise and improve contrast.
4. Detect plate-like regions with edges and contours.
5. Apply thresholding and morphological preprocessing.
6. Run multiple Tesseract page-segmentation modes.
7. Normalize uppercase alphanumeric output.
8. Compare the plate with the active watchlist.
9. Produce an access decision and alert state.
10. Record the event with confidence, direction, image reference, operator, and timestamp.

Unreadable or low-confidence plates are not treated as authorized visitors. They require manual verification.

## Hardware Alerts

The application produces a hardware-neutral alert state. `Blocked` and `Unauthorized` decisions request an audible and visual alert. A production installation should use a separate controller with an opto-isolated relay or protected driver, a regulated low-voltage supply, fuse protection, and an operator acknowledgement button.

See [HARDWARE_INTEGRATION.md](HARDWARE_INTEGRATION.md) for wiring architecture, commissioning, safety, and controller guidance.

## Academic Design Blueprint

The complete Chapter 3 methodology and system design blueprint is available in [CHAPTER_3_SYSTEM_DESIGN_BLUEPRINT.md](CHAPTER_3_SYSTEM_DESIGN_BLUEPRINT.md). It covers the research methodology, architecture, RBAC matrix, database schema, immutable audit design, dashboard layouts, hardware alerts, and evaluation criteria.

## Testing

Run all tests with:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

The test suite covers OCR normalization, access decisions, alert policy, RBAC permissions, protected routes, watchlist authorization, invalid credentials, and application workflow behavior.

## Project Structure

```text
app.py                         Flask routes and application workflow
main.py                        Database connection and schema migration
anpr.py                        OpenCV and Tesseract OCR pipeline
access_control.py              Plate normalization and access decisions
alerts.py                      Alert policy and hardware-neutral alert state
rbac.py                        Centralized role permissions
auth_security.py               Argon2id hashing and legacy hash migration
manage_users.py                Secure command-line account provisioning
templates/                     Role dashboards and application views
static/css/style.css           Bootstrap-aligned design system
Procfile                       Gunicorn start command for Railway / Render
runtime.txt                    Python 3.11 runtime pin
Aptfile                        System package: tesseract-ocr
render.yaml                    Render deployment blueprint
CHAPTER_3_SYSTEM_DESIGN_BLUEPRINT.md  Academic methodology and design
HARDWARE_INTEGRATION.md        Buzzer and relay integration guide
test_*.py                      Automated tests
```

## Security Notes

- Never commit `.env` or real credentials.
- Never use the development server for production deployment.
- Use HTTPS and secure cookies in a deployed environment.
- Keep the database on a private network.
- Rotate the Flask secret and database credentials before deployment.
- Review and back up audit data according to POLAC policy.
- Do not connect a physical buzzer or gate mechanism directly to a computer port or unprotected GPIO pin.
