import os
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


class DatabaseConnection:
    """Unified wrapper for MySQL and PostgreSQL connections."""

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
        return MySQLError

    def cursor(self, dictionary=False):
        if self._db_type == "postgresql":
            cursor = self._conn.cursor()
            return PgDictCursor(cursor) if dictionary else cursor
        return self._conn.cursor(dictionary=dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def is_connected(self):
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
    return os.getenv("DB_TYPE", "mysql")


def _connection_kwargs_from_database_url(database_url):
    """Parse a DATABASE_URL into connect() kwargs for either MySQL or PostgreSQL."""
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
    1. DATABASE_URL (auto-injected by Railway/Render), supports mysql:// and postgres://
    2. MYSQL_* env vars (Railway MySQL plugin), or PG* vars (Render PostgreSQL)
    3. Legacy APNR_DB_* env vars (local development)
    4. Sensible localhost defaults
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        kwargs, db_type = _connection_kwargs_from_database_url(database_url)
        if db_type == "postgresql":
            import pg8000
            conn = pg8000.connect(**kwargs)
            return DatabaseConnection(conn, "postgresql")
        conn = mysql.connector.connect(**kwargs)
        return DatabaseConnection(conn, "mysql")

    # Detect PostgreSQL vs MySQL from env
    if os.getenv("DATABASE_URL", "").startswith(("postgres", "postgresql")):
        db_type = "postgresql"
    else:
        db_type = os.getenv("DB_TYPE", "mysql")

    if db_type == "postgresql":
        import pg8000
        conn = pg8000.connect(
            host=os.getenv("PGHOST", os.getenv("MYSQL_HOST", os.getenv("APNR_DB_HOST", "127.0.0.1"))),
            user=os.getenv("PGUSER", os.getenv("MYSQL_USER", os.getenv("APNR_DB_USER", "postgres"))),
            password=os.getenv("PGPASSWORD", os.getenv("MYSQL_PASSWORD", os.getenv("APNR_DB_PASSWORD", ""))),
            database=os.getenv("PGDATABASE", os.getenv("MYSQL_DATABASE", os.getenv("APNR_DB_NAME", "postgres"))),
            port=int(os.getenv("PGPORT", os.getenv("MYSQL_PORT", os.getenv("APNR_DB_PORT", "5432")))),
        )
        return DatabaseConnection(conn, "postgresql")

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


def initialize_schema():
    """Create the tables required by the current Flask application if absent."""
    connection = cursor = None
    try:
        connection = create_connection()
        db_type = connection.db_type
        cursor = connection.cursor()

        if db_type == "postgresql":
            _initialize_schema_postgresql(cursor)
        else:
            _initialize_schema_mysql(cursor)

        connection.commit()
        return True
    except (MySQLError, Exception) as error:
        if connection is not None:
            connection.rollback()
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
