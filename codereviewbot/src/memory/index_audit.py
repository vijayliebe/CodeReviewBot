"""Index coverage audit — verify chunking and Chroma persistence for a repo."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import chromadb

from src.memory.code_chunker import chunk_file
from src.memory.index_manifest import git_head_sha, load_manifest
from src.memory.indexer import scan_supported_files


@dataclass
class SymbolHit:
    name: str
    chunk_type: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class FileAuditRow:
    rel_path: str
    local_code_chunks: int
    local_imports: int
    chroma_code_chunks: int
    chroma_imports: int
    issues: list[str] = field(default_factory=list)


@dataclass
class AuditReport:
    repo_id: str
    repo_path: Path
    never_indexed: bool
    stale: bool
    disk_files: int
    manifest_files: int
    chroma_files: int
    total_local_code_chunks: int
    total_local_imports: int
    total_chroma_code_chunks: int
    total_chroma_imports: int
    manifest_code_chunks: int
    manifest_imports: int
    last_sha: str | None
    current_sha: str | None
    zero_chunk_files: list[str] = field(default_factory=list)
    not_in_manifest: list[str] = field(default_factory=list)
    orphan_manifest_files: list[str] = field(default_factory=list)
    chroma_missing_files: list[str] = field(default_factory=list)
    count_mismatch_files: list[str] = field(default_factory=list)
    rows: list[FileAuditRow] = field(default_factory=list)
    symbol_hits: list[SymbolHit] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """True when indexing coverage is broken (not informational zero-chunk files)."""
        symbol_missing = any(
            r.rel_path.startswith("(symbol:") and r.issues for r in self.rows
        )
        return (
            self.never_indexed
            or bool(self.not_in_manifest)
            or bool(self.orphan_manifest_files)
            or bool(self.chroma_missing_files)
            or bool(self.count_mismatch_files)
            or symbol_missing
        )

    @property
    def has_warnings(self) -> bool:
        return self.stale or bool(self.zero_chunk_files)


def _local_chunk_counts(file_path: Path) -> tuple[int, int]:
    chunks = chunk_file(file_path)
    code = sum(1 for c in chunks if c.chunk_type != "import")
    imports = sum(1 for c in chunks if c.chunk_type == "import")
    return code, imports


def _chroma_counts_by_file(db_path: Path, repo_id: str) -> tuple[dict[str, int], dict[str, int]]:
    code_by_file: dict[str, int] = defaultdict(int)
    imports_by_file: dict[str, int] = defaultdict(int)
    client = chromadb.PersistentClient(path=str(db_path))

    for collection_name, target in (
        ("code_chunks", code_by_file),
        ("code_imports", imports_by_file),
    ):
        try:
            collection = client.get_collection(collection_name)
            results = collection.get(where={"repo_id": repo_id}, include=["metadatas"])
            for meta in results.get("metadatas") or []:
                fp = meta.get("file_path")
                if fp:
                    target[fp] += 1
        except Exception:
            continue

    return dict(code_by_file), dict(imports_by_file)


def search_symbols(db_path: Path, repo_id: str, symbols: list[str]) -> list[SymbolHit]:
    if not symbols:
        return []

    client = chromadb.PersistentClient(path=str(db_path))
    hits: list[SymbolHit] = []
    try:
        collection = client.get_collection("code_chunks")
    except Exception:
        return hits

    for symbol in symbols:
        symbol = symbol.strip()
        if not symbol:
            continue
        try:
            results = collection.get(
                where={"$and": [{"repo_id": repo_id}, {"name": symbol}]},
                include=["metadatas"],
            )
            for meta in results.get("metadatas") or []:
                hits.append(
                    SymbolHit(
                        name=symbol,
                        chunk_type=meta.get("type", "?"),
                        file_path=meta.get("file_path", "?"),
                        start_line=int(meta.get("start_line", 0)),
                        end_line=int(meta.get("end_line", 0)),
                    )
                )
        except Exception:
            continue
    return hits


def audit_repo(
    repo_path: Path,
    db_path: Path,
    repo_id: str,
    *,
    symbols: list[str] | None = None,
    include_ok_files: bool = False,
) -> AuditReport:
    """Compare disk chunking, manifest coverage, and Chroma vectors for a repo."""
    scan_root = repo_path.resolve()
    disk_hashes = scan_supported_files(scan_root)
    manifest = load_manifest(db_path, repo_id)
    manifest_hashes = dict(manifest.get("file_hashes", {})) if manifest else {}
    stats = (manifest or {}).get("stats", {})

    chroma_code, chroma_imports = _chroma_counts_by_file(db_path, repo_id)
    chroma_files = set(chroma_code) | set(chroma_imports)

    last_sha = manifest.get("last_indexed_sha") if manifest else None
    current_sha = git_head_sha(scan_root)
    stale = bool(last_sha and current_sha and last_sha != current_sha)

    report = AuditReport(
        repo_id=repo_id,
        repo_path=scan_root,
        never_indexed=manifest is None,
        stale=stale,
        disk_files=len(disk_hashes),
        manifest_files=len(manifest_hashes),
        chroma_files=len(chroma_files),
        total_local_code_chunks=0,
        total_local_imports=0,
        total_chroma_code_chunks=sum(chroma_code.values()),
        total_chroma_imports=sum(chroma_imports.values()),
        manifest_code_chunks=int(stats.get("code_chunks", 0)),
        manifest_imports=int(stats.get("imports", 0)),
        last_sha=last_sha,
        current_sha=current_sha,
    )

    for rel_path in sorted(disk_hashes):
        file_path = scan_root / rel_path
        local_code, local_imports = _local_chunk_counts(file_path)
        c_code = chroma_code.get(rel_path, 0)
        c_imports = chroma_imports.get(rel_path, 0)

        report.total_local_code_chunks += local_code
        report.total_local_imports += local_imports

        issues: list[str] = []
        if local_code == 0 and local_imports == 0:
            issues.append("zero_chunks (module-level-only or unparseable)")
            report.zero_chunk_files.append(rel_path)
        if manifest is not None and rel_path not in manifest_hashes:
            issues.append("not_in_manifest")
            report.not_in_manifest.append(rel_path)
        if manifest is not None and rel_path in manifest_hashes:
            if c_code == 0 and local_code > 0:
                issues.append("chroma_missing_code_chunks")
                report.chroma_missing_files.append(rel_path)
            elif c_code != local_code:
                issues.append(f"count_mismatch local={local_code} chroma={c_code}")
                report.count_mismatch_files.append(rel_path)

        if issues or include_ok_files:
            report.rows.append(
                FileAuditRow(
                    rel_path=rel_path,
                    local_code_chunks=local_code,
                    local_imports=local_imports,
                    chroma_code_chunks=c_code,
                    chroma_imports=c_imports,
                    issues=issues,
                )
            )

    for rel_path in sorted(set(manifest_hashes) - set(disk_hashes)):
        report.orphan_manifest_files.append(rel_path)
        report.rows.append(
            FileAuditRow(
                rel_path=rel_path,
                local_code_chunks=0,
                local_imports=0,
                chroma_code_chunks=chroma_code.get(rel_path, 0),
                chroma_imports=chroma_imports.get(rel_path, 0),
                issues=["orphan_manifest (file removed from disk)"],
            )
        )

    if symbols:
        report.symbol_hits = search_symbols(db_path, repo_id, symbols)
        requested = {s.strip() for s in symbols if s.strip()}
        found = {h.name for h in report.symbol_hits}
        for symbol in sorted(requested - found):
            report.rows.append(
                FileAuditRow(
                    rel_path=f"(symbol:{symbol})",
                    local_code_chunks=0,
                    local_imports=0,
                    chroma_code_chunks=0,
                    chroma_imports=0,
                    issues=[f"symbol_not_found: {symbol!r}"],
                )
            )

    return report


def format_audit_report(report: AuditReport, *, verbose: bool = False) -> str:
    lines = [
        f"Repo:              {report.repo_id}",
        f"Path:              {report.repo_path}",
        f"Disk files:        {report.disk_files}",
        f"Manifest files:    {report.manifest_files}",
        f"Chroma files:      {report.chroma_files}",
        f"Local chunks:      {report.total_local_code_chunks} code, {report.total_local_imports} imports",
        f"Chroma vectors:    {report.total_chroma_code_chunks} code, {report.total_chroma_imports} imports",
        f"Manifest stats:    {report.manifest_code_chunks} code, {report.manifest_imports} imports",
        f"Last SHA:          {report.last_sha or '(none)'}",
        f"Current SHA:       {report.current_sha or '(non-git)'}",
    ]

    if report.never_indexed:
        lines.append("Status:            NEVER INDEXED — run `codereviewbot index`")
    elif report.stale:
        lines.append("Status:            STALE — HEAD advanced since last index")
    else:
        lines.append("Status:            up-to-date")

    if report.disk_files != report.manifest_files and not report.never_indexed:
        lines.append(
            f"Coverage gap:      disk={report.disk_files} vs manifest={report.manifest_files}"
        )

    if report.symbol_hits:
        lines.append("\nSymbol hits:")
        for hit in report.symbol_hits:
            lines.append(
                f"  {hit.name:20} {hit.chunk_type:8} {hit.file_path}:{hit.start_line}-{hit.end_line}"
            )

    problem_rows = [r for r in report.rows if r.issues]
    if problem_rows:
        lines.append(f"\nIssues ({len(problem_rows)}):")
        for row in problem_rows:
            issue_text = "; ".join(row.issues)
            if row.rel_path.startswith("(symbol:"):
                lines.append(f"  {issue_text}")
            else:
                lines.append(
                    f"  {row.rel_path}: local={row.local_code_chunks}/{row.local_imports} "
                    f"chroma={row.chroma_code_chunks}/{row.chroma_imports} — {issue_text}"
                )
    elif not report.never_indexed:
        lines.append("\nNo file-level issues detected.")

    if verbose:
        ok_rows = [r for r in report.rows if not r.issues and not r.rel_path.startswith("(symbol:")]
        if ok_rows:
            lines.append(f"\nOK files ({len(ok_rows)}):")
            for row in ok_rows[:50]:
                lines.append(
                    f"  {row.rel_path}: local={row.local_code_chunks}/{row.local_imports} "
                    f"chroma={row.chroma_code_chunks}/{row.chroma_imports}"
                )
            if len(ok_rows) > 50:
                lines.append(f"  ... and {len(ok_rows) - 50} more")

    return "\n".join(lines)
