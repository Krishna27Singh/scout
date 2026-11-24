"""Create the initial Scout schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=False),
        sa.Column("primary_language", sa.String(length=64), nullable=True),
        sa.Column(
            "topics",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("stars", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "maintainer_activity_score",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            server_default=sa.text("'curated'"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_queried_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_repositories"),
    )
    op.create_index("ix_repositories_github_id", "repositories", ["github_id"], unique=True)
    op.create_index("ix_repositories_owner", "repositories", ["owner"])
    op.create_index("ix_repositories_full_name", "repositories", ["full_name"], unique=True)
    op.create_index("ix_repositories_primary_language", "repositories", ["primary_language"])

    op.create_table(
        "issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column(
            "labels",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("assignees_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("comments_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("has_linked_pr", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_actionable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("embedding", HALFVEC(384), nullable=True),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("github_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"],
            ["repositories.id"],
            name="fk_issues_repo_id_repositories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_issues"),
        sa.UniqueConstraint("repo_id", "number", name="uq_issues_repo_id_number"),
        sa.UniqueConstraint("html_url", name="uq_issues_html_url"),
    )
    op.create_index("ix_issues_github_id", "issues", ["github_id"], unique=True)
    op.create_index("ix_issues_repo_id", "issues", ["repo_id"])
    op.create_index("ix_issues_state", "issues", ["state"])
    op.create_index("ix_issues_is_actionable", "issues", ["is_actionable"])
    op.create_index("ix_issues_github_created_at", "issues", ["github_created_at"])
    op.create_index("ix_issues_github_updated_at", "issues", ["github_updated_at"])
    op.create_index(
        "ix_issues_embedding_hnsw",
        "issues",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.create_index("ix_issues_search_tsv", "issues", ["search_tsv"], postgresql_using="gin")
    op.create_index("ix_issues_labels", "issues", ["labels"], postgresql_using="gin")

    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_key", sa.String(length=128), nullable=False),
        sa.Column(
            "preferred_languages",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "preferred_topics",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "preferred_orgs",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "excluded_labels",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "excluded_topics",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "experience_level",
            sa.String(length=32),
            server_default=sa.text("'intermediate'"),
            nullable=False,
        ),
        sa.Column("raw_notes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_profiles"),
    )
    op.create_index("ix_user_profiles_session_key", "user_profiles", ["session_key"], unique=True)

    op.create_table(
        "dismissed_issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name="fk_dismissed_issues_issue_id_issues",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_profile_id"],
            ["user_profiles.id"],
            name="fk_dismissed_issues_user_profile_id_user_profiles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dismissed_issues"),
        sa.UniqueConstraint(
            "user_profile_id",
            "issue_id",
            name="uq_dismissed_issues_user_profile_id_issue_id",
        ),
    )
    op.create_index(
        "ix_dismissed_issues_user_profile_id",
        "dismissed_issues",
        ["user_profile_id"],
    )
    op.create_index("ix_dismissed_issues_issue_id", "dismissed_issues", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_dismissed_issues_issue_id", table_name="dismissed_issues")
    op.drop_index("ix_dismissed_issues_user_profile_id", table_name="dismissed_issues")
    op.drop_table("dismissed_issues")
    op.drop_index("ix_user_profiles_session_key", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_index("ix_issues_labels", table_name="issues")
    op.drop_index("ix_issues_search_tsv", table_name="issues")
    op.drop_index("ix_issues_embedding_hnsw", table_name="issues")
    op.drop_index("ix_issues_github_updated_at", table_name="issues")
    op.drop_index("ix_issues_github_created_at", table_name="issues")
    op.drop_index("ix_issues_is_actionable", table_name="issues")
    op.drop_index("ix_issues_state", table_name="issues")
    op.drop_index("ix_issues_repo_id", table_name="issues")
    op.drop_index("ix_issues_github_id", table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_repositories_primary_language", table_name="repositories")
    op.drop_index("ix_repositories_full_name", table_name="repositories")
    op.drop_index("ix_repositories_owner", table_name="repositories")
    op.drop_index("ix_repositories_github_id", table_name="repositories")
    op.drop_table("repositories")
    op.execute("DROP EXTENSION IF EXISTS vector")
