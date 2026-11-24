from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    primary_language: Mapped[str | None] = mapped_column(String(64), index=True)
    topics: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    stars: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    maintainer_activity_score: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0.0")
    )
    source: Mapped[str] = mapped_column(
        String(32), default="curated", server_default=text("'curated'")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_issues_repo_id_number"),
        Index(
            "ix_issues_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        Index("ix_issues_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_issues_labels", "labels", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    repo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str] = mapped_column(Text, unique=True)
    state: Mapped[str] = mapped_column(
        String(16), default="open", server_default=text("'open'"), index=True
    )
    labels: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    assignees_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    comments_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    has_linked_pr: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_actionable: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(384), nullable=True)
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))",
            persisted=True,
        ),
        nullable=False,
    )
    github_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    github_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    preferred_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    preferred_topics: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    preferred_orgs: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    excluded_labels: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    excluded_topics: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    experience_level: Mapped[str] = mapped_column(
        String(32), default="intermediate", server_default=text("'intermediate'")
    )
    raw_notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DismissedIssue(Base):
    __tablename__ = "dismissed_issues"
    __table_args__ = (
        UniqueConstraint(
            "user_profile_id", "issue_id", name="uq_dismissed_issues_user_profile_id_issue_id"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
