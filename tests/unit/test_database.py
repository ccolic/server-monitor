import pytest
from server_monitor.database import DatabaseType


def test_database_type_enum():
    assert DatabaseType.SQLITE == "sqlite"
    assert DatabaseType.POSTGRES == "postgres"
    assert DatabaseType.MYSQL == "mysql"


def test_database_type_str():
    assert str(DatabaseType.SQLITE) == "sqlite"
    assert str(DatabaseType.POSTGRES) == "postgres"


def test_database_type_membership():
    assert "sqlite" in DatabaseType._value2member_map_
    assert "postgres" in DatabaseType._value2member_map_
    assert "mysql" in DatabaseType._value2member_map_
