from backend.app.application import cases as dev_cases
from backend.app.infrastructure.db.models import OrganizationMembership


class DevIdentitySession:
    def __init__(self):
        self.rows = {}
        self.commits = 0

    def get(self, model, key):
        return self.rows.get((model, key))

    def scalar(self, _statement):
        return next(
            (value for (model, _key), value in self.rows.items() if model is OrganizationMembership),
            None,
        )

    def add(self, row):
        self.rows[(type(row), row.id)] = row

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


def test_development_principal_has_active_organization_membership():
    db = DevIdentitySession()

    organization, user = dev_cases.ensure_dev_identity(db)
    membership = db.scalar(None)

    assert membership is not None
    assert membership.organization_id == organization.id
    assert membership.user_id == user.id
    assert membership.role == "bioinformatician"
    assert membership.status == "ACTIVE"

    organization_again, user_again = dev_cases.ensure_dev_identity(db)

    assert organization_again is organization
    assert user_again is user
    assert db.scalar(None) is membership
