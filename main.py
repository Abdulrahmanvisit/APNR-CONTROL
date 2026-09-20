import os
import sqlite3
from urllib.parse import urlparse

import mysql.connector
from mysql.connector import Error as MySQLError


class PgDictCursor:
    """Wrap a pg8000 cursor to yield dict rows like mysql-connector's dictionary=True."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def execute(self, query, params=()):
        return self._cursor.execute(query, params)

    def fetchall(self):
        if self._cursor.description is None:
            return []
        columns = [col[0] for col in self._cursor.description]
        return [dict(zip(columns, row)) for row in self._cursor.fetchall()]

    def fetchone(self):
        if self._cursor.description is None:
            return None
        columns = [col[0] for col in self._cursor.description]
        row = self._cursor.fetchone()
        return dict(zip(columns, row)) if row else None

    def close(self):
        self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class SqliteDictCursor:
    """Wrap a sqlite3 cursor to accept %s-style params and optionally yield dict rows."""

    def __init__(self, cursor, dictionary=True):
        self._cursor = cursor
        self._dictionary = dictionary

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def _convert_query(self, query):
        return query.replace("%s", "?")

    def execute(self, query, params=()):
        converted = self._convert_query(query)
        return self._cursor.execute(converted, params)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows or self._cursor.description is None:
            return []
        if not self._dictionary:
            return rows
        columns = [col[0] for col in self._cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return None
        if not self._dictionary:
            return row
        columns = [col[0] for col in self._cursor.description]
        return dict(zip(columns, row))

    def close(self):
        self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class DatabaseConnection:
    """Unified wrapper for MySQL, PostgreSQL, and SQLite connections."""

    def __init__(self, conn, db_type):
        self._conn = conn
        self._db_type = db_type

    @property
    def db_type(self):
        return self._db_type

    @property
    def Error(self):
        """Return the appropriate Error exception class for this database."""
        if self._db_type == "postgresql":
            import pg8000
            return pg8000.Error
        if self._db_type == "sqlite":
            return sqlite3.Error
        return MySQLError

    def cursor(self, dictionary=False):
        if self._db_type == "postgresql":
            cursor = self._conn.cursor()
            return PgDictCursor(cursor) if dictionary else cursor
        if self._db_type == "sqlite":
            cursor = self._conn.cursor()
            return SqliteDictCursor(cursor, dictionary=dictionary)
        return self._conn.cursor(dictionary=dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def is_connected(self):
        if self._db_type == "sqlite":
            return True
        if self._db_type == "postgresql":
            return not self._conn.isclosed if hasattr(self._conn, "isclosed") else True
        return self._conn.is_connected()


def _detect_db_type(database_url=""):
    """Detect database type from DATABASE_URL scheme or DB_TYPE env var."""
    if database_url:
        lowered = database_url.lower()
        if lowered.startswith("postgres://") or lowered.startswith("postgresql://"):
            return "postgresql"
        if lowered.startswith("mysql://") or lowered.startswith("mysql://"):
            return "mysql"
        if lowered.startswith("sqlite://") or lowered.startswith("sqlite:///"):
            return "sqlite"
    return os.getenv("DB_TYPE", "mysql")


def _connection_kwargs_from_database_url(database_url):
    """Parse a DATABASE_URL into connect() kwargs for either MySQL, PostgreSQL, or SQLite."""
    lowered = database_url.lower()
    if lowered.startswith("sqlite://") or lowered.startswith("sqlite:///"):
        path = database_url[lowered.index("sqlite://") + len("sqlite://"):]
        if path.startswith("/"):
            path = path[1:]
        return {"path": path or "apnr_local.db"}, "sqlite"

    parsed = urlparse(database_url)
    kwargs = {
        "host": parsed.hostname,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/") or None,
        "port": parsed.port or (5432 if parsed.scheme in ("postgres", "postgresql") else 3306),
    }
    query = dict(
        pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair
    ) if parsed.query else {}

    db_type = "postgresql" if parsed.scheme in ("postgres", "postgresql") else "mysql"
    if db_type == "mysql":
        if query.get("ssl", "").lower() in ("true", "1", "required") or \
           query.get("ssl-mode", "").upper() in ("REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"):
            ca = query.get("sslca") or query.get("ssl-ca") or os.getenv("MYSQL_SSL_CA")
            if ca:
                kwargs["ssl_ca"] = ca
            else:
                kwargs["ssl_disabled"] = False
        elif query.get("ssl", "").lower() in ("false", "0", "disabled"):
            kwargs["ssl_disabled"] = True
    else:
        if query.get("sslmode", "").lower() in ("require", "verify-ca", "verify-full"):
            kwargs["ssl_context"] = True

    return kwargs, db_type


def create_connection():
    """Create and return a connection to the APNR database.

    Connection details are resolved in this order:
    1. DATABASE_URL (auto-injected by Railway/Render), supports mysql://, postgres://, sqlite://
    2. MYSQL_* env vars (Railway MySQL plugin), or PG* vars (Render PostgreSQL)
    3. Legacy APNR_DB_* env vars (local development)
    4. SQLite fallback (local file-based database in the application directory)
    5. Sensible MySQL localhost defaults
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        kwargs, db_type = _connection_kwargs_from_database_url(database_url)
        if db_type == "postgresql":
            import pg8000
            conn = pg8000.connect(**kwargs)
            return DatabaseConnection(conn, "postgresql")
        if db_type == "sqlite":
            conn = sqlite3.connect(_sqlite_path(kwargs.get("path", "apnr_local.db")))
            return DatabaseConnection(conn, "sqlite")
        conn = mysql.connector.connect(**kwargs)
        return DatabaseConnection(conn, "mysql")

    # Detect PostgreSQL vs MySQL vs SQLite from env
    db_type = os.getenv("DB_TYPE", "mysql")
    if db_type == "sqlite" or (os.getenv("DATABASE_URL", "").startswith(("sqlite",))):
        db_type = "sqlite"
    elif db_type == "postgresql" or (os.getenv("DATABASE_URL", "").startswith(("postgres", "postgresql"))):
        db_type = "postgresql"
    else:
        db_type = "mysql"

    # SQLite fallback when no external database env vars are configured.
    # This lets the app run (with login + auto-provisioning) inside containers
    # like Render without a database add-on attached yet.
    _has_external = bool(
        os.getenv("MYSQL_HOST") or os.getenv("APNR_DB_HOST") or os.getenv("PGHOST")
    )
    if db_type == "sqlite" or (db_type == "mysql" and not _has_external):
        # Try local defaults MySQL first (useful for local dev with a running MySQL)
        if db_type == "mysql" and _has_external is False:
            host = os.getenv("MYSQL_HOST", os.getenv("APNR_DB_HOST", "127.0.0.1"))
            try:
                test_conn = mysql.connector.connect(
                    host=host,
                    user=os.getenv("MYSQL_USER", os.getenv("APNR_DB_USER", "root")),
                    password=os.getenv("MYSQL_PASSWORD", os.getenv("APNR_DB_PASSWORD", "root1234")),
                    database=os.getenv("MYSQL_DATABASE", os.getenv("APNR_DB_NAME", "apnr_db")),
                    port=int(os.getenv("MYSQL_PORT", os.getenv("APNR_DB_PORT", "3306"))),
                    connection_timeout=3,
                )
                test_conn.close()
                # MySQL is available — fall through to MySQL path below
            except Exception:
                # MySQL unavailable — use SQLite fallback
                conn = sqlite3.connect(_sqlite_path(os.getenv("SQLITE_PATH", "apnr_local.db")))
                return DatabaseConnection(conn, "sqlite")

        if db_type == "sqlite":
            conn = sqlite3.connect(_sqlite_path(os.getenv("SQLITE_PATH", "apnr_local.db")))
            return DatabaseConnection(conn, "sqlite")

    # MySQL path
    host = os.getenv("MYSQL_HOST", os.getenv("APNR_DB_HOST", "127.0.0.1"))
    user = os.getenv("MYSQL_USER", os.getenv("APNR_DB_USER", "root"))
    password = os.getenv("MYSQL_PASSWORD", os.getenv("APNR_DB_PASSWORD", "root1234"))
    database = os.getenv("MYSQL_DATABASE", os.getenv("APNR_DB_NAME", "apnr_db"))
    raw_port = os.getenv("MYSQL_PORT", os.getenv("APNR_DB_PORT", "3306"))

    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("MYSQL_PORT (or APNR_DB_PORT) must be an integer") from error

    conn = mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
    )
    return DatabaseConnection(conn, "mysql")


def _sqlite_path(path_env):
    """Resolve the SQLite database file path, creating parent dirs if needed.

    On Render (where RENDER is set), uses /tmp which is always writable
    and persists for the container's lifetime.
    """
    if os.getenv("RENDER"):
        path = "/tmp/apnr_local.db"
    else:
        path = os.path.abspath(path_env)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path


def initialize_schema():
    """Create the tables required by the current Flask application if absent."""
    connection = cursor = None
    try:
        connection = create_connection()
        db_type = connection.db_type
        cursor = connection.cursor()

        if db_type == "postgresql":
            _initialize_schema_postgresql(cursor)
        elif db_type == "sqlite":
            _initialize_schema_sqlite(cursor)
        else:
            _initialize_schema_mysql(cursor)

        connection.commit()
        return True
    except (MySQLError, Exception) as error:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        print(f"Schema initialization warning: {error}")
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()
    return False


def _initialize_schema_mysql(cursor):
    """MySQL-specific schema creation and migration."""
    statements = (
        """CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(80) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'Operator',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_first_login BOOLEAN NOT NULL DEFAULT FALSE,
            failed_attempts SMALLINT NOT NULL DEFAULT 0,
            locked_until TIMESTAMP NULL,
            last_login_at TIMESTAMP NULL
        )""",
        """CREATE TABLE IF NOT EXISTS watchlist (
            id INT AUTO_INCREMENT PRIMARY KEY,
            plate_number VARCHAR(20) NOT NULL UNIQUE,
            category VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            notes VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS detection_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            plate_number VARCHAR(20) NOT NULL,
            confidence DECIMAL(5, 2) NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type VARCHAR(10) NOT NULL DEFAULT 'Entry',
            image_path VARCHAR(255),
            alert_generated BOOLEAN NOT NULL DEFAULT FALSE,
            operator_username VARCHAR(80)
        )""",
    )
    for statement in statements:
        cursor.execute(statement)

    for column, definition in (
        ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("is_first_login", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("failed_attempts", "SMALLINT NOT NULL DEFAULT 0"),
        ("locked_until", "TIMESTAMP NULL"),
        ("last_login_at", "TIMESTAMP NULL"),
    ):
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = %s",
            (column,),
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")


def _initialize_schema_sqlite(cursor):
    """SQLite-specific schema creation and migration."""
    statements = (
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(80) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'Operator',
            is_active INTEGER NOT NULL DEFAULT 1,
            is_first_login INTEGER NOT NULL DEFAULT 0,
            failed_attempts SMALLINT NOT NULL DEFAULT 0,
            locked_until TIMESTAMP NULL,
            last_login_at TIMESTAMP NULL
        )""",
        """CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number VARCHAR(20) NOT NULL UNIQUE,
            category VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            notes VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS detection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number VARCHAR(20) NOT NULL,
            confidence DECIMAL(5, 2) NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type VARCHAR(10) NOT NULL DEFAULT 'Entry',
            image_path VARCHAR(255),
            alert_generated INTEGER NOT NULL DEFAULT 0,
            operator_username VARCHAR(80)
        )""",
    )
    for statement in statements:
        cursor.execute(statement)

    # SQLite uses INTEGER for BOOLEAN (0/1), which differs from MySQL/Postgres.
    # All columns are created with appropriate types in the table definitions above.


def _initialize_schema_postgresql(cursor):
    """PostgreSQL-specific schema creation and migration."""
    statements = (
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'Operator',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_first_login BOOLEAN NOT NULL DEFAULT FALSE,
            failed_attempts SMALLINT NOT NULL DEFAULT 0,
            locked_until TIMESTAMP NULL,
            last_login_at TIMESTAMP NULL
        )""",
        """CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            plate_number VARCHAR(20) NOT NULL UNIQUE,
            category VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            notes VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS detection_logs (
            id SERIAL PRIMARY KEY,
            plate_number VARCHAR(20) NOT NULL,
            confidence DECIMAL(5, 2) NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'Visitor',
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            event_type VARCHAR(10) NOT NULL DEFAULT 'Entry',
            image_path VARCHAR(255),
            alert_generated BOOLEAN NOT NULL DEFAULT FALSE,
            operator_username VARCHAR(80)
        )""",
    )
    for statement in statements:
        cursor.execute(statement)

    for column, definition in (
        ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("is_first_login", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("failed_attempts", "SMALLINT NOT NULL DEFAULT 0"),
        ("locked_until", "TIMESTAMP NULL"),
        ("last_login_at", "TIMESTAMP NULL"),
    ):
        # PostgreSQL: check if column exists via information_schema
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = %s",
            (column,),
        )
        if cursor.fetchone()[0] == 0:
            pg_type = definition.split()[0]
            if pg_type == "BOOLEAN":
                pg_def = "BOOLEAN"
            elif pg_type == "SMALLINT":
                pg_def = "SMALLINT"
            elif pg_type == "TIMESTAMP":
                pg_def = "TIMESTAMP"
            else:
                pg_def = pg_type
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column} {pg_def}")


def main():
    connection = None
    try:
        connection = create_connection()
        initialize_schema()
        print(f"Connected to the {'PostgreSQL' if connection.db_type == 'postgresql' else 'MySQL'} APNR database.")
    except Exception as error:
        print(f"Database connection failed: {error}")
    finally:
        if connection is not None and connection.is_connected():
            connection.close()
            print("Database connection closed.")


if __name__ == "__main__":
    main()
