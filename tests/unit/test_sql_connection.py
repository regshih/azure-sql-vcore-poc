import struct
from unittest.mock import MagicMock

import pyodbc
import pytest
from azure.core.credentials import AccessToken
from sqlalchemy.pool import NullPool, QueuePool

from src.configuration.settings import Settings
from src.database.connection import SQL_TOKEN_ATTRIBUTE, connection_creator, make_engine, pack_token
from src.resilience.errors import OperationFailure


def test_fresh_utf16_token_per_physical_connection_and_tls() -> None:
    settings = Settings(sql_server="sql.example.invalid", sql_database="synthetic")
    credential = MagicMock()
    credential.get_token.side_effect = [
        AccessToken("first", 9999999999),
        AccessToken("second", 9999999999),
    ]
    connect = MagicMock()
    creator = connection_creator(settings, credential, connect)
    creator()
    creator()
    assert credential.get_token.call_count == 2
    first, second = connect.call_args_list
    assert first.kwargs["attrs_before"][SQL_TOKEN_ATTRIBUTE] == pack_token("first")
    assert second.kwargs["attrs_before"][SQL_TOKEN_ATTRIBUTE] == pack_token("second")
    encoded = pack_token("second")
    assert struct.unpack("<I", encoded[:4])[0] == len("second".encode("utf-16-le"))
    assert encoded[4:].decode("utf-16-le") == "second"
    assert "Encrypt=yes;TrustServerCertificate=no" in first.args[0]
    assert "PWD=" not in first.args[0]
    assert "UID=" not in first.args[0]


def test_bounded_pool_and_scoped_no_pool_engine_do_not_connect() -> None:
    settings = Settings(sql_pool_size=2, sql_pool_max_overflow=0, sql_pool_timeout_seconds=0.1)
    creator = MagicMock()
    pooled = make_engine(settings, creator)
    unpooled = make_engine(settings, creator, pooled=False)
    assert isinstance(pooled.pool, QueuePool)
    assert pooled.pool.size() == 2
    assert isinstance(unpooled.pool, NullPool)
    creator.assert_not_called()
    pooled.dispose()
    unpooled.dispose()


def test_login_timeout_is_distinct_from_command_timeout() -> None:
    settings = Settings(sql_server="sql.example.invalid", sql_database="synthetic")
    credential = MagicMock()
    credential.get_token.return_value = AccessToken("synthetic-token", 9999999999)
    connect = MagicMock(side_effect=pyodbc.Error("HYT00", "synthetic login timeout"))
    with pytest.raises(OperationFailure) as error:
        connection_creator(settings, credential, connect)()
    assert error.value.failure.outcome == "database_connection_timeout"
    assert error.value.failure.retryable is True
