import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

_source_assets = Path(__file__).resolve().parents[2] / "sql"
SQL_ROOT = Path(
    os.environ.get(
        "SQL_ASSET_DIRECTORY",
        str(_source_assets if _source_assets.is_dir() else Path.cwd() / "sql"),
    )
)
MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    sql: str


def discover(directory: Path = SQL_ROOT / "migrations") -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError("Migration names must be ordered four-digit versions.")
        content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        migrations.append(
            Migration(match[1], hashlib.sha256(content.encode("utf-8")).hexdigest(), content)
        )
    versions = [int(migration.version) for migration in migrations]
    if not versions or versions != list(range(1, len(versions) + 1)):
        raise ValueError("Migration versions must be unique and contiguous starting at 0001.")
    return tuple(migrations)


def batches(sql: str) -> tuple[str, ...]:
    return tuple(
        part.strip() for part in re.split(r"(?im)^\s*GO\s*(?:--[^\r\n]*)?$", sql) if part.strip()
    )


def migrate(engine: Engine, directory: Path = SQL_ROOT / "migrations") -> list[str]:
    migrations = discover(directory)
    applied: list[str] = []
    with engine.begin() as connection:
        locked: int = connection.execute(
            text(
                "SET NOCOUNT ON; DECLARE @r int; EXEC @r=sys.sp_getapplock "
                "@Resource='poc-schema-migration',@LockMode='Exclusive',@LockOwner='Transaction',"
                "@LockTimeout=30000; SELECT @r"
            )
        ).scalar_one()
        if int(locked) < 0:
            raise ValueError("Unable to acquire migration lock.")
        connection.execute(
            text(
                "IF OBJECT_ID('dbo.SchemaMigrations','U') IS NULL "
                "CREATE TABLE dbo.SchemaMigrations (version char(4) NOT NULL PRIMARY KEY,"
                "checksum char(64) NOT NULL, "
                "applied_at datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME())"
            )
        )
        ledger: dict[str, str] = dict(
            connection.execute(text("SELECT version,checksum FROM dbo.SchemaMigrations")).tuples()
        )
        known = {migration.version for migration in migrations}
        if set(ledger) - known:
            raise ValueError("Database has migrations unknown to this application version.")
        if sorted(ledger) != [migration.version for migration in migrations[: len(ledger)]]:
            raise ValueError("Migration ledger is not an ordered prefix.")
        for migration in migrations:
            existing = ledger.get(migration.version)
            if existing is not None:
                if existing != migration.checksum:
                    raise ValueError(
                        "Applied migration checksum mismatch; migrations are immutable."
                    )
                continue
            for statement in batches(migration.sql):
                connection.exec_driver_sql(statement)
            connection.execute(
                text("INSERT dbo.SchemaMigrations(version,checksum) VALUES (:v,:c)"),
                {"v": migration.version, "c": migration.checksum},
            )
            applied.append(migration.version)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("ALTER DATABASE CURRENT SET QUERY_STORE = ON")
        connection.exec_driver_sql(
            "ALTER DATABASE CURRENT SET QUERY_STORE (OPERATION_MODE = READ_WRITE, "
            "MAX_STORAGE_SIZE_MB = 256, CLEANUP_POLICY = (STALE_QUERY_THRESHOLD_DAYS = 30))"
        )
    return applied
