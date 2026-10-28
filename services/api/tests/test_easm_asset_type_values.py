"""The asset type is stored as the database enum's own values, not the Python member names.

The enum in the database (migration 024) holds 'domain', 'ip', ...; SQLAlchemy sends the member NAME ('DOMAIN') unless told to send the value, and Postgres refused it:
invalid input value for enum external_asset_type: "DOMAIN". Every scan that found anything failed when saving, so the page never showed a result.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.easm import ExternalAsset, ExternalAssetType
from sqlalchemy.dialects import postgresql

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "024_easm.sql"


def sent_to_postgres(kind: ExternalAssetType) -> object:
    column_type = ExternalAsset.__table__.c.asset_type.type
    return column_type.bind_processor(postgresql.dialect())(kind)


@pytest.mark.parametrize("kind", list(ExternalAssetType))
def test_each_asset_type_is_sent_as_its_value(kind):
    assert sent_to_postgres(kind) == kind.value


def test_every_value_is_one_the_database_enum_has():
    sql = MIGRATION.read_text(encoding="utf-8")
    enum_block = sql.split("CREATE TYPE external_asset_type AS ENUM (", 1)[1].split(");", 1)[0]
    in_database = {part.strip().strip("'") for part in enum_block.replace("\n", " ").split(",")}
    assert {kind.value for kind in ExternalAssetType} <= in_database
