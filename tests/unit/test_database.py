from server_monitor.database import DatabaseType


def test_database_type_enum():
    assert DatabaseType.SQLITE == "sqlite"
    assert DatabaseType.POSTGRESQL == "postgresql"


def test_database_type_str():
    assert DatabaseType.SQLITE.value == "sqlite"
    assert DatabaseType.POSTGRESQL.value == "postgresql"


def test_database_type_membership():
    assert "sqlite" in DatabaseType._value2member_map_
    assert "postgresql" in DatabaseType._value2member_map_
