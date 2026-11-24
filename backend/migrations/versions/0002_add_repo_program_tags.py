"""Add repository program tags and ingestion priority.

Revision ID: 0002_add_repo_program_tags
Revises: 0001_initial_schema
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_repo_program_tags"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column(
            "program_tags",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("100"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_repositories_program_tags",
        "repositories",
        ["program_tags"],
        postgresql_using="gin",
    )
    op.create_index("ix_repositories_priority", "repositories", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_repositories_priority", table_name="repositories")
    op.drop_index("ix_repositories_program_tags", table_name="repositories")
    op.drop_column("repositories", "priority")
    op.drop_column("repositories", "program_tags")
