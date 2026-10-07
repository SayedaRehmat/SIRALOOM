from uuid import uuid4

from backend.app.api.v1.auth import _lock_organization_membership_mutations


class _Dialect:
    def __init__(self, name: str):
        self.name = name


class _Bind:
    def __init__(self, name: str):
        self.dialect = _Dialect(name)


class _LockDb:
    def __init__(self, dialect: str):
        self.bind = _Bind(dialect)
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))


def test_membership_mutation_lock_is_transaction_scoped_on_postgresql():
    db = _LockDb("postgresql")
    organization_id = uuid4()

    _lock_organization_membership_mutations(db, organization_id)

    assert len(db.calls) == 1
    statement, params = db.calls[0]
    assert "pg_advisory_xact_lock" in statement
    assert params["lock_key"] == int.from_bytes(
        organization_id.bytes[:8], byteorder="big", signed=True
    )


def test_membership_mutation_lock_is_not_used_for_non_postgresql():
    db = _LockDb("sqlite")

    _lock_organization_membership_mutations(db, uuid4())

    assert db.calls == []
