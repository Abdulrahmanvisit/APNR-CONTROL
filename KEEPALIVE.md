# Keep-Alive Setup Guide

To prevent overnight authentication failures on Render Free-tier hosting, you need to:

1. **Keep the web service awake** (prevent cold starts)
2. **Keep database connections warm** (prevent stale socket errors)
3. **Use persistent sessions** (prevent overnight session cookie expiry)

## 1. Uptime Monitoring (Keep Service Awake)

Configure a free external uptime monitor to ping `/api/v1/health` every 5-10 minutes.

### Option A: UptimeRobot (Recommended - Free)

1. Go to https://uptimerobot.com/ and create a free account.
2. Click **Add New Monitor**.
3. Choose **HTTP(s)** as monitor type.
4. Set the URL to `https://apnr-control.onrender.com/api/v1/health`.
5. Set the monitoring interval to **5 minutes**.
6. Optionally set alert contacts to receive notifications if the service goes down.

### Option B: Cron-job.org (Free Alternative)

1. Go to https://cron-job.org/ and create a free account.
2. Click **Create Cronjob**.
3. Set the URL to `https://apnr-control.onrender.com/api/v1/health`.
4. Set the schedule to every 5 minutes (`* * * * *` with 5-minute cron: `*/5 * * * *`).
5. Enable the cronjob.

## 2. Session Persistence

The application is configured with:
- `PERMANENT_SESSION_LIFETIME` = 365 days
- `SESSION_COOKIE_MAX_AGE` = 365 days
- `SESSION_COOKIE_SAMESITE` = "Lax"
- `SESSION_COOKIE_HTTPONLY` = True

This means session cookies remain valid for up to 1 year, preventing overnight logouts.

## 3. Database Connection Resilience

The application implements automatic retry logic:
- Up to 3 connection retries with exponential backoff (1s, 2s, 3s delays)
- `connection_timeout=10` seconds for MySQL connections
- `connection.ping(reconnect=True, attempts=3, delay=1)` for automatic reconnect
- SQLite fallback when MySQL is unavailable

When using an external MySQL provider (e.g., Aiven):
- Configure `wait_timeout` to 28800+ seconds (8 hours) on the MySQL server
- Or rely on the application-level retry logic to reconnect automatically

## 4. Render Health Check Path

The Render health check is configured to use `/api/v1/health` which:
- Pings the database with `SELECT 1`
- Returns HTTP 200 with `database: connected` when healthy
- Returns HTTP 503 with `database: error: ...` when degraded

This lightweight endpoint is safe to call frequently for keep-alive purposes.
