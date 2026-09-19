import os
from urllib.parse import urlparse

import mysql.connector
from mysql.connector import Error


def _connection_kwargs_from_database_url(database_url):
    """Parse a DATABASE_URL (e.g. mysql://user:pass@host:port/dbname) into connect() kwargs."""
    parsed = urlparse(database_url)
    kwargs = {
        "host": parsed.hostname,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/") or None,
        "port": parsed.port or 3306,
    }
    query = dict(pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair) if parsed.query else {}
    if query.get("ssl", "").lower() in ("true", "1", "required") or query.get("ssl-mode", "").upper() in ("REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"):
        ca = query.get("sslca") or query.get("ssl-ca") or os.getenv("MYSQL_SSL_CA")
        if ca:
            kwargs["ssl_ca"] = ca
        else:
            kwargs["ssl_disabled"] = False
    elif query.get("ssl", "").lower() in ("false", "0", "disabled"):
        kwargs["ssl_disabled"] = True
    return kwargs


def create_connection():
    """Create and return a connection to the APNR MySQL database.

    Connection details are resolved in this order:
    1. DATABASE_URL, if provided (e.g. by Railway), is parsed directly.
    2. The MYSQL_* environment variables provided by a Railway MySQL service.
    3. The legacy APNR_DB_* environment variables, for local development.
    4. Sensible localhost defaults, for local development without any env vars.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        kwargs = _connection_kwargs_from_database_url(database_url)
        return mysql.connector.connect(**kwargs)

    host = os.getenv("MYSQL_HOST", os.getenv("APNR_DB_HOST", "127.0.0.1"))
    user = os.getenv("MYSQL_USER", os.getenv("APNR_DB_USER", "root"))
    password = os.getenv("MYSQL_PASSWORD", os.getenv("APNR_DB_PASSWORD", "root1234"))
    database = os.getenv("MYSQL_DATABASE", os.getenv("APNR_DB_NAME", "apnr_db"))
    raw_port = os.getenv("MYSQL_PORT", os.getenv("APNR_DB_PORT", "3306"))

    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("MYSQL_PORT (or APNR_DB_PORT) must be an integer") from error

    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
    )


def initialize_schema():
    """Create the tables required by the current Flask application if absent."""
    connection = cursor = None
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
    try:
        connection = create_connection()
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'detection_logs' "
            "AND column_name = 'event_type'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE detection_logs ADD COLUMN event_type VARCHAR(10) NOT NULL DEFAULT 'Entry'")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'detection_logs' "
            "AND column_name = 'image_path'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE detection_logs ADD COLUMN image_path VARCHAR(255)")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'detection_logs' "
            "AND column_name = 'alert_generated'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE detection_logs ADD COLUMN alert_generated BOOLEAN NOT NULL DEFAULT FALSE")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'detection_logs' "
            "AND column_name = 'operator_username'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE detection_logs ADD COLUMN operator_username VARCHAR(80)")
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
        connection.commit()
        return True
    except Error:
        if connection is not None:
            connection.rollback()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()
    return False


def main():
    connection = None
    try:
        connection = create_connection()
        initialize_schema()
        print("Connected to the APNR database.")
    except Error as error:
        print(f"Database connection failed: {error}")
    finally:
        if connection is not None and connection.is_connected():
            connection.close()
            print("Database connection closed.")


if __name__ == "__main__":
    main()