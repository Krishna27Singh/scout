from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.schemas.search import SearchFilters


@dataclass(frozen=True)
class BenchmarkRepository:
    full_name: str
    owner: str
    name: str
    language: str
    topics: tuple[str, ...]
    program_tags: tuple[str, ...]
    maintainer_activity_score: float


@dataclass(frozen=True)
class BenchmarkIssue:
    repo_full_name: str
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    updated_days_ago: int
    comments_count: int = 0


@dataclass(frozen=True)
class EvalCase:
    query: str
    filters: SearchFilters
    relevant_keys: tuple[tuple[str, int], ...]


BENCHMARK_REPOSITORIES = (
    BenchmarkRepository(
        "sugarlabs/musicblocks",
        "sugarlabs",
        "musicblocks",
        "TypeScript",
        ("education", "visual-programming", "music"),
        ("gsoc",),
        0.94,
    ),
    BenchmarkRepository(
        "sympy/sympy",
        "sympy",
        "sympy",
        "Python",
        ("symbolic-mathematics", "computer-algebra"),
        ("gsoc",),
        0.96,
    ),
    BenchmarkRepository(
        "apache/datafusion",
        "apache",
        "datafusion",
        "Rust",
        ("query-engine", "arrow", "dataframe"),
        ("gsoc",),
        0.92,
    ),
    BenchmarkRepository(
        "opencv/opencv",
        "opencv",
        "opencv",
        "C++",
        ("computer-vision", "image-processing"),
        ("gsoc",),
        0.90,
    ),
    BenchmarkRepository(
        "arxlang/doukimd",
        "arxlang",
        "doukimd",
        "Python",
        ("markdown", "documentation-tooling"),
        ("gsoc",),
        0.78,
    ),
    BenchmarkRepository(
        "fastapi/fastapi",
        "fastapi",
        "fastapi",
        "Python",
        ("web", "api", "async"),
        ("ecosystem",),
        0.98,
    ),
    BenchmarkRepository(
        "pgvector/pgvector",
        "pgvector",
        "pgvector",
        "C",
        ("postgresql", "vector-search", "database"),
        ("ecosystem",),
        0.89,
    ),
    BenchmarkRepository(
        "vercel/next.js",
        "vercel",
        "next.js",
        "TypeScript",
        ("react", "web", "frontend"),
        ("ecosystem",),
        0.95,
    ),
)

BENCHMARK_ISSUES = (
    BenchmarkIssue(
        "sugarlabs/musicblocks",
        1_800_001,
        "Audio blocks stop playback after changing instruments",
        (
            "Reproduce by starting a project with two instrument blocks and switching the active "
            "instrument during playback. The audio engine should keep scheduled notes and resume "
            "at the next beat without restarting the project."
        ),
        ("good first issue", "audio"),
        12,
        8,
    ),
    BenchmarkIssue(
        "sugarlabs/musicblocks",
        1_800_002,
        "Snap nested blocks to the correct visual-programming connection",
        (
            "When dragging a nested block near a compatible connection, calculate the nearest "
            "anchor and preserve the existing parent relationship. Add a regression test for "
            "blocks moved between two nested stacks."
        ),
        ("help wanted", "blocks"),
        18,
        4,
    ),
    BenchmarkIssue(
        "sugarlabs/musicblocks",
        1_800_003,
        "Fix a spelling mistake in the music lesson guide",
        (
            "The beginner lesson has a typo in the second paragraph. Correct the spelling and "
            "rebuild the documentation site."
        ),
        ("documentation",),
        3,
    ),
    BenchmarkIssue(
        "sugarlabs/musicblocks",
        1_800_004,
        "Dark theme button has a small CSS alignment issue",
        (
            "The theme switch is two pixels too low on narrow screens. Update the stylesheet and "
            "verify the responsive layout."
        ),
        ("frontend", "css"),
        6,
        2,
    ),
    BenchmarkIssue(
        "sympy/sympy",
        1_800_005,
        "Piecewise integration drops a condition at a symbolic boundary",
        (
            "Integrating a piecewise expression over a symbolic interval can return an "
            "antiderivative with the wrong boundary condition. Preserve assumptions while "
            "splitting the interval and add a focused regression test."
        ),
        ("good first issue", "integrals"),
        7,
        11,
    ),
    BenchmarkIssue(
        "sympy/sympy",
        1_800_006,
        "Improve sparse polynomial factorization performance",
        (
            "The sparse polynomial path spends most of its time converting exponent dictionaries "
            "before factorization. Avoid the redundant conversion and compare runtime on "
            "multivariate polynomials with few terms."
        ),
        ("performance", "polynomials"),
        14,
        6,
    ),
    BenchmarkIssue(
        "sympy/sympy",
        1_800_007,
        "Correct one punctuation typo in the installation documentation",
        (
            "A comma is missing from the installation page. This is a documentation-only change "
            "with no code behavior impact."
        ),
        ("documentation",),
        5,
    ),
    BenchmarkIssue(
        "sympy/sympy",
        1_800_008,
        "Old simplification benchmark still uses deprecated helper",
        (
            "This stale benchmark was reported a long time ago and the maintainer team has not "
            "revisited it. The proposed change is no longer applicable to the current "
            "simplification pipeline."
        ),
        ("stale",),
        840,
    ),
    BenchmarkIssue(
        "apache/datafusion",
        1_800_009,
        "Push parquet predicates into row group scans",
        (
            "A filter on a parquet column is currently evaluated after decoding every row group. "
            "Push supported predicates into row group pruning and verify that the scan skips "
            "irrelevant pages without changing query results."
        ),
        ("help wanted", "execution"),
        9,
        9,
    ),
    BenchmarkIssue(
        "apache/datafusion",
        1_800_010,
        "Reduce allocations when planning nested SQL joins",
        (
            "The logical planner repeatedly clones join expressions for a query with several "
            "nested joins. Reuse immutable expressions and preserve the existing join ordering "
            "and filter pushdown behavior."
        ),
        ("sql", "planner"),
        16,
        5,
    ),
    BenchmarkIssue(
        "apache/datafusion",
        1_800_011,
        "Fix a typo in the parquet user guide",
        (
            "The parquet guide contains a misspelled word in the examples section. Correct the "
            "text without modifying code."
        ),
        ("documentation",),
        4,
    ),
    BenchmarkIssue(
        "apache/datafusion",
        1_800_012,
        "DataFusion query planner panics on deeply nested expressions",
        (
            "A report from an old release describes a planner panic for a query shape that was "
            "removed during a refactor. There has been no maintainer activity on this report for "
            "many months."
        ),
        ("stale",),
        720,
    ),
    BenchmarkIssue(
        "opencv/opencv",
        1_800_013,
        "CUDA image transform loses pixels at tile boundaries",
        (
            "The CUDA image transform kernel leaves a narrow strip unchanged when image "
            "dimensions are not multiples of the tile size. Adjust the boundary mask and add a "
            "non-aligned image regression test."
        ),
        ("good first issue", "cuda"),
        10,
        7,
    ),
    BenchmarkIssue(
        "opencv/opencv",
        1_800_014,
        "Feature detector should handle an empty input mask",
        (
            "Passing an empty mask to the feature detector should return no keypoints rather than "
            "reading uninitialized pixels. Add coverage for empty and all-zero masks."
        ),
        ("help wanted", "features2d"),
        19,
        3,
    ),
    BenchmarkIssue(
        "opencv/opencv",
        1_800_015,
        "Correct typo in the computer vision tutorial",
        (
            "Fix a single spelling error in the image processing tutorial. There are no "
            "implementation changes requested."
        ),
        ("documentation",),
        2,
    ),
    BenchmarkIssue(
        "opencv/opencv",
        1_800_016,
        "Legacy image codec module has no active maintainer",
        (
            "This old report concerns a codec that is no longer enabled by default. It has not "
            "been triaged recently and the proposed interface is obsolete."
        ),
        ("stale",),
        900,
    ),
    BenchmarkIssue(
        "arxlang/doukimd",
        1_800_017,
        "Markdown parser mishandles nested fenced code blocks",
        (
            "When a fenced code example contains a nested fence, the parser closes the outer "
            "block too early. Track fence length and delimiter type so rendered Markdown "
            "preserves the full example."
        ),
        ("good first issue", "parser"),
        8,
        4,
    ),
    BenchmarkIssue(
        "arxlang/doukimd",
        1_800_018,
        "Preserve heading anchors while rendering Markdown links",
        (
            "The renderer should generate stable heading anchors when converting relative "
            "Markdown links. Add tests for duplicate headings and percent-encoded fragments."
        ),
        ("markdown",),
        21,
        2,
    ),
    BenchmarkIssue(
        "arxlang/doukimd",
        1_800_019,
        "Documentation page has a broken punctuation example",
        (
            "The README example has an extra period after a Markdown link. Update the "
            "documentation text only."
        ),
        ("documentation",),
        3,
    ),
    BenchmarkIssue(
        "fastapi/fastapi",
        1_800_020,
        "Async dependency override is not reused across a request",
        (
            "An async dependency override is awaited more than once for the same request when "
            "it is shared by nested dependencies. Preserve request-scoped caching while "
            "honoring dependency overrides."
        ),
        ("good first issue", "dependencies"),
        5,
        14,
    ),
    BenchmarkIssue(
        "fastapi/fastapi",
        1_800_021,
        "OpenAPI schema omits a response header from a nested router",
        (
            "A response header declared on an included router should appear in the generated "
            "OpenAPI operation. Add a regression case for nested routers and keep the schema "
            "deterministic."
        ),
        ("openapi",),
        13,
        6,
    ),
    BenchmarkIssue(
        "fastapi/fastapi",
        1_800_022,
        "Fix one spelling mistake in the deployment docs",
        (
            "The deployment instructions have a typo in the environment variable section. "
            "This issue is documentation only."
        ),
        ("documentation",),
        4,
    ),
    BenchmarkIssue(
        "fastapi/fastapi",
        1_800_023,
        "Documentation site CSS breaks the navigation on mobile",
        (
            "The sidebar overlaps the article content at a narrow viewport. Adjust the CSS "
            "breakpoint and test the docs site layout at mobile widths."
        ),
        ("frontend", "css"),
        7,
    ),
    BenchmarkIssue(
        "pgvector/pgvector",
        1_800_024,
        "Halfvec cosine distance gives incorrect HNSW ordering",
        (
            "The half-precision vector path should order nearest neighbors consistently with "
            "cosine distance. Check normalization and add an HNSW regression test with vectors "
            "that differ by a small angle."
        ),
        ("good first issue", "hnsw"),
        11,
        10,
    ),
    BenchmarkIssue(
        "pgvector/pgvector",
        1_800_025,
        "Improve memory use while building an HNSW index",
        (
            "Index construction retains temporary neighbor buffers longer than needed on a "
            "large relation. Release per-layer buffers after insertion and verify recall "
            "remains stable."
        ),
        ("performance", "indexing"),
        22,
        3,
    ),
    BenchmarkIssue(
        "pgvector/pgvector",
        1_800_026,
        "Correct a typo in the vector index documentation",
        "There is a spelling mistake in the index option description. This is a docs-only fix.",
        ("documentation",),
        2,
    ),
    BenchmarkIssue(
        "vercel/next.js",
        1_800_027,
        "Deduplicate fetch requests in a server component cache",
        (
            "Two server components requesting the same resource during one render should share "
            "the cached promise. Keep cache invalidation correct across requests and add "
            "coverage for concurrent rendering."
        ),
        ("good first issue", "server-components"),
        6,
        12,
    ),
    BenchmarkIssue(
        "vercel/next.js",
        1_800_028,
        "CSS grid layout shifts after client navigation",
        (
            "A frontend grid briefly changes column width after client-side navigation. "
            "Reproduce with a responsive stylesheet and prevent the layout shift without "
            "disabling streaming."
        ),
        ("frontend", "css"),
        8,
    ),
    BenchmarkIssue(
        "vercel/next.js",
        1_800_029,
        "Fix a typo in the TypeScript routing guide",
        (
            "The routing guide has a misspelled word in a TypeScript code sample. The request "
            "is limited to documentation."
        ),
        ("documentation",),
        1,
    ),
    BenchmarkIssue(
        "vercel/next.js",
        1_800_030,
        "Legacy router stylesheet regression has gone stale",
        (
            "The report refers to an unsupported version of the legacy router. There has been "
            "no recent maintainer activity and the proposed CSS workaround is obsolete."
        ),
        ("stale",),
        760,
    ),
)

EVAL_CASES = (
    EvalCase(
        "Keep music block playback synchronized when instruments change",
        SearchFilters(repo_owners=["sugarlabs"], excluded_labels=["documentation"]),
        (("sugarlabs/musicblocks", 1_800_001),),
    ),
    EvalCase(
        "Snap nested visual programming blocks to the right connection",
        SearchFilters(repo_owners=["sugarlabs"], program_tags=["gsoc"]),
        (("sugarlabs/musicblocks", 1_800_002),),
    ),
    EvalCase(
        "Symbolic integration loses piecewise conditions at interval boundaries",
        SearchFilters(repo_owners=["sympy"], excluded_labels=["documentation"]),
        (("sympy/sympy", 1_800_005),),
    ),
    EvalCase(
        "Optimize sparse multivariate polynomial factorization",
        SearchFilters(repo_full_names=["sympy/sympy"], program_tags=["gsoc"]),
        (("sympy/sympy", 1_800_006),),
    ),
    EvalCase(
        "Skip parquet row groups by pushing predicates into the DataFusion scan",
        SearchFilters(repo_owners=["apache"], program_tags=["gsoc"]),
        (("apache/datafusion", 1_800_009),),
    ),
    EvalCase(
        "Reduce query planner allocations for nested SQL joins",
        SearchFilters(repo_owners=["apache"], excluded_topics=["documentation"]),
        (("apache/datafusion", 1_800_010),),
    ),
    EvalCase(
        "CUDA image transform tile boundary pixels are not updated",
        SearchFilters(repo_owners=["opencv"], program_tags=["gsoc"]),
        (("opencv/opencv", 1_800_013),),
    ),
    EvalCase(
        "Feature detector should return safely for an empty mask",
        SearchFilters(repo_full_names=["opencv/opencv"], excluded_labels=["documentation"]),
        (("opencv/opencv", 1_800_014),),
    ),
    EvalCase(
        "Parse nested fenced code blocks in Markdown documents",
        SearchFilters(repo_owners=["arxlang"], excluded_topics=["documentation"]),
        (("arxlang/doukimd", 1_800_017),),
    ),
    EvalCase(
        "Reuse an asynchronous dependency override within a FastAPI request",
        SearchFilters(repo_owners=["fastapi"], excluded_labels=["documentation"]),
        (("fastapi/fastapi", 1_800_020),),
    ),
    EvalCase(
        "Halfvec cosine nearest neighbor ordering using HNSW",
        SearchFilters(repo_owners=["pgvector"], program_tags=["ecosystem"]),
        (("pgvector/pgvector", 1_800_024), ("pgvector/pgvector", 1_800_025)),
    ),
    EvalCase(
        "Share cached fetch promises between Next.js server components",
        SearchFilters(repo_owners=["vercel"], excluded_labels=["documentation"]),
        (("vercel/next.js", 1_800_027),),
    ),
)


def build_benchmark_dataset() -> tuple[tuple[BenchmarkRepository, ...], tuple[BenchmarkIssue, ...]]:
    return BENCHMARK_REPOSITORIES, tuple(BENCHMARK_ISSUES)


def issue_updated_at(issue: BenchmarkIssue, now: datetime) -> datetime:
    reference = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    return reference - timedelta(days=issue.updated_days_ago)
