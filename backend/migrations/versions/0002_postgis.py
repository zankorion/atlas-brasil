"""geometria PostGIS para territórios (somente PostgreSQL)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # em SQLite as malhas são servidas a partir de data/geo/*.geojson.gz
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("ALTER TABLE territory ADD COLUMN IF NOT EXISTS geom geometry(MultiPolygon, 4674)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_territory_geom ON territory USING gist (geom)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_territory_geom")
    op.execute("ALTER TABLE territory DROP COLUMN IF EXISTS geom")
