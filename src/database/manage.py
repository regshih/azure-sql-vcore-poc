import argparse
import json
import os
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.configuration.settings import Settings
from src.database.connection import connection_creator, credential_for, make_engine
from src.database.dataset_state import dataset_state, full_dataset_fingerprint
from src.database.migrations import SQL_ROOT, migrate
from src.database.seed import MAX_ROWS, PROFILES, seed_database
from src.resilience.errors import classify
from src.telemetry.metrics import silence_dependency_logs


def validated_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError("A valid UUID is required.") from None


def parse_rows(value: str) -> int:
    try:
        rows = int(value)
        if not 1 <= rows <= MAX_ROWS:
            raise ValueError
        return rows
    except ValueError:
        raise argparse.ArgumentTypeError("Rows must be between 1 and 3000000.") from None


def parse_seed(value: str) -> int:
    try:
        seed = int(value)
        if not 0 <= seed <= 2147483647:
            raise ValueError
        return seed
    except ValueError:
        raise argparse.ArgumentTypeError("Seed must be between 0 and 2147483647.") from None


def runtime_user_sql(object_id: str) -> str:
    sid = UUID(object_id).bytes_le.hex()
    return f"CREATE USER [poc_runtime] WITH SID=0x{sid}, TYPE=E;"


def grant_runtime(engine: Engine, object_id: str) -> None:
    sid = UUID(object_id).bytes_le
    with engine.begin() as connection:
        administrator_sid = connection.execute(text("SELECT SUSER_SID()")).scalar_one_or_none()
        if administrator_sid is not None and bytes(administrator_sid) == sid:
            raise ValueError("Bootstrap and runtime identities must be different.")
        existing = connection.execute(
            text("SELECT sid FROM sys.database_principals WHERE name='poc_runtime'")
        ).scalar_one_or_none()
        if existing is not None and bytes(existing) != sid:
            raise ValueError("Existing runtime user SID differs; refusing to change identity.")
        if (
            connection.execute(
                text("SELECT IS_ROLEMEMBER('db_owner','poc_runtime')")
            ).scalar_one_or_none()
            == 1
        ):
            raise ValueError("Runtime identity must not be a database owner.")
        if existing is None:
            connection.exec_driver_sql(runtime_user_sql(object_id))
        connection.exec_driver_sql(
            "IF DATABASE_PRINCIPAL_ID('poc_runtime_role') IS NULL CREATE ROLE poc_runtime_role"
        )
        connection.exec_driver_sql(
            "IF IS_ROLEMEMBER('poc_runtime_role','poc_runtime') <> 1 "
            "ALTER ROLE poc_runtime_role ADD MEMBER poc_runtime"
        )
        for table in (
            "Products",
            "WorkItems",
            "WorkItemLines",
            "Activity",
            "IdempotencyKeys",
            "SchemaMigrations",
            "DatasetVersions",
            "RuntimeConfiguration",
        ):
            connection.exec_driver_sql(f"GRANT SELECT ON OBJECT::dbo.{table} TO poc_runtime_role")
        connection.exec_driver_sql(
            "GRANT UPDATE (stock_units) ON OBJECT::dbo.Products TO poc_runtime_role"
        )
        for table in ("WorkItems", "WorkItemLines", "Activity", "IdempotencyKeys"):
            connection.exec_driver_sql(f"GRANT INSERT ON OBJECT::dbo.{table} TO poc_runtime_role")


def grant_observer(engine: Engine, object_id: str, runtime_object_id: str) -> None:
    sid = UUID(object_id).bytes_le
    runtime_sid = UUID(runtime_object_id).bytes_le
    if sid == runtime_sid:
        raise ValueError("Observer and runtime identities must be different.")
    with engine.begin() as connection:
        administrator_sid = connection.execute(text("SELECT SUSER_SID()")).scalar_one_or_none()
        if administrator_sid is None or bytes(administrator_sid) == sid:
            raise ValueError("Observer identity must be distinct from the verified administrator.")
        stored_runtime_sid = connection.execute(
            text("SELECT sid FROM sys.database_principals WHERE name='poc_runtime'")
        ).scalar_one_or_none()
        if stored_runtime_sid is None or bytes(stored_runtime_sid) != runtime_sid:
            raise ValueError("A matching runtime identity must be configured first.")
        existing = (
            connection.execute(
                text("SELECT sid,type FROM sys.database_principals WHERE name='poc_observer'")
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None and (bytes(existing["sid"]) != sid or existing["type"] != "E"):
            raise ValueError("Existing observer identity differs; refusing to change it.")
        if (
            connection.execute(
                text("SELECT IS_ROLEMEMBER('db_owner','poc_observer')")
            ).scalar_one_or_none()
            == 1
        ):
            raise ValueError("Observer identity must not be a database owner.")
        if existing is not None:
            excessive_permissions = connection.execute(
                text(
                    "SELECT CASE WHEN EXISTS (SELECT 1 FROM sys.database_role_members "
                    "WHERE member_principal_id=DATABASE_PRINCIPAL_ID('poc_observer')) "
                    "OR EXISTS (SELECT 1 FROM sys.database_permissions "
                    "WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID('poc_observer') "
                    "AND (class<>0 OR permission_name NOT IN ('CONNECT','VIEW DATABASE STATE') "
                    "OR state<>'G')) "
                    "OR EXISTS (SELECT 1 FROM sys.schemas "
                    "WHERE principal_id=DATABASE_PRINCIPAL_ID('poc_observer')) "
                    "OR EXISTS (SELECT 1 FROM sys.database_principals "
                    "WHERE owning_principal_id=DATABASE_PRINCIPAL_ID('poc_observer')) "
                    "THEN 1 ELSE 0 END"
                )
            ).scalar_one()
            if int(excessive_permissions) != 0:
                raise ValueError(
                    "Existing observer has roles, ownership or unexpected permissions."
                )
        else:
            connection.exec_driver_sql(
                f"CREATE USER [poc_observer] WITH SID=0x{sid.hex()}, TYPE=E;"
            )
        connection.exec_driver_sql("GRANT CONNECT TO [poc_observer]")
        connection.exec_driver_sql("GRANT VIEW DATABASE STATE TO [poc_observer]")


def tune(engine: Engine, mode: str, allow_unsafe: bool = False) -> dict[str, str]:
    if mode not in {"baseline", "index", "query", "both"}:
        raise ValueError("Unknown tuning mode.")
    if mode in {"baseline", "query"} and not allow_unsafe:
        raise ValueError("Removing the test index requires --allow-unsafe-test.")
    with engine.begin() as connection:
        index_file = "index.sql" if mode in {"index", "both"} else "baseline.sql"
        connection.exec_driver_sql((SQL_ROOT / "tuning" / index_file).read_text(encoding="utf-8"))
        connection.execute(
            text("UPDATE dbo.RuntimeConfiguration SET value=:mode WHERE [key]='tuning_mode'"),
            {"mode": mode},
        )
    return {"status": "tuned", "mode": mode}


def fingerprint(engine: Engine) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection:
        with connection.begin():
            return {
                "status": "fingerprinted",
                **dataset_state(connection),
                **full_dataset_fingerprint(connection),
            }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Entra-authenticated Azure SQL POC administration."
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser(
        "fingerprint",
        help="Read-only full business-row fingerprint; stop all workload writers first.",
    )
    for name in ("seed", "bootstrap"):
        child = commands.add_parser(name)
        child.add_argument("--size", choices=tuple(PROFILES), default="small")
        child.add_argument("--seed", type=parse_seed, default=42)
        child.add_argument("--rows", type=parse_rows)
        if name == "seed":
            child.add_argument("--reset", action="store_true")
            child.add_argument("--allow-destructive-tests", action="store_true")
            child.add_argument("--confirm-poc", action="store_true")
        if name == "bootstrap":
            child.add_argument(
                "--runtime-object-id",
                type=validated_uuid,
                help="Runtime principal UUID; defaults to environment RUNTIME_OBJECT_ID.",
            )
            child.add_argument(
                "--observer-object-id",
                type=validated_uuid,
                help="Optional observer UUID; defaults to environment OBSERVER_OBJECT_ID.",
            )
    tuning = commands.add_parser("tune")
    tuning.add_argument("--mode", choices=("baseline", "index", "query", "both"), required=True)
    tuning.add_argument("--allow-unsafe-test", action="store_true")
    return result


def main() -> int:
    silence_dependency_logs()
    arguments = parser().parse_args()
    credential = None
    engine: Engine | None = None
    try:
        if (
            arguments.command == "seed"
            and arguments.reset
            and not (arguments.allow_destructive_tests and arguments.confirm_poc)
        ):
            raise ValueError("Reset requires --allow-destructive-tests and --confirm-poc.")
        if arguments.command == "bootstrap" and arguments.runtime_object_id is None:
            raw_object_id = os.environ.get("RUNTIME_OBJECT_ID")
            if not raw_object_id:
                raise ValueError("RUNTIME_OBJECT_ID or --runtime-object-id is required.")
            try:
                arguments.runtime_object_id = UUID(raw_object_id)
            except ValueError:
                raise ValueError("RUNTIME_OBJECT_ID must contain a valid UUID.") from None
        if arguments.command == "bootstrap":
            if arguments.observer_object_id is None:
                raw_observer_id = os.environ.get("OBSERVER_OBJECT_ID")
                if raw_observer_id:
                    try:
                        arguments.observer_object_id = UUID(raw_observer_id)
                    except ValueError:
                        raise ValueError("OBSERVER_OBJECT_ID must contain a valid UUID.") from None
            if arguments.observer_object_id == arguments.runtime_object_id:
                raise ValueError("Observer and runtime identities must be different.")
        settings = Settings()
        if arguments.command == "seed" and arguments.reset and not settings.poc_mode:
            raise ValueError("Reset is disabled when POC_MODE is false.")
        credential = credential_for(settings)
        engine = make_engine(settings, connection_creator(settings, credential))
        output: dict[str, Any]
        if arguments.command == "migrate":
            output = {"status": "migrated", "versions": migrate(engine)}
        elif arguments.command == "fingerprint":
            output = fingerprint(engine)
        elif arguments.command == "seed":
            output = seed_database(
                engine,
                size=arguments.size,
                seed=arguments.seed,
                rows=arguments.rows,
                reset=arguments.reset,
                allow_destructive_tests=arguments.allow_destructive_tests,
                confirm_poc=arguments.confirm_poc,
            )
        elif arguments.command == "bootstrap":
            versions = migrate(engine)
            grant_runtime(engine, str(arguments.runtime_object_id))
            if arguments.observer_object_id is not None:
                grant_observer(
                    engine, str(arguments.observer_object_id), str(arguments.runtime_object_id)
                )
            output = seed_database(
                engine, size=arguments.size, seed=arguments.seed, rows=arguments.rows
            )
            output.update(
                {
                    "status": "bootstrapped",
                    "migrations_applied": versions,
                    "observer_configured": arguments.observer_object_id is not None,
                }
            )
        else:
            output = tune(engine, arguments.mode, arguments.allow_unsafe_test)
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception as error:
        failure = classify(error)
        # Deliberately omit exception text, configuration and principal identifiers.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "category": failure.outcome,
                    "code": "invalid_administration_request"
                    if isinstance(error, ValueError)
                    else failure.code,
                    "action": arguments.command,
                    "hint": (
                        "Verify SQL settings, RUNTIME_OBJECT_ID, optional OBSERVER_OBJECT_ID, "
                        "distinct least-privilege identities, Entra permissions, "
                        "migration checksums, "
                        "seed bounds, synthetic marker, destructive-reset confirmations "
                        "(--allow-destructive-tests --confirm-poc with POC_MODE=true) "
                        "and tuning flags."
                    ),
                }
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if credential is not None:
            credential.close()


if __name__ == "__main__":
    raise SystemExit(main())
