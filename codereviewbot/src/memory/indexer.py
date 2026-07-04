import os
import re
from pathlib import Path
import chromadb
from src.memory.code_chunker import chunk_file, CodeChunk
from src.memory.index_manifest import (
    diff_files,
    file_hash,
    git_changed_files,
    git_head_sha,
    git_is_ancestor,
    load_manifest,
    save_manifest,
    build_manifest_entry,
)


SUPPORTED_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".tf", ".tfvars",
                  ".swift", ".kt", ".dart"}
SKIP_DIR_PARTS = {".venv", ".git", "__pycache__", "node_modules", "dist", "build", "chroma_db"}


def scan_supported_files(scan_root: Path) -> dict[str, str]:
    """Walk the repo and return {relative_path: sha256} for every supported file."""
    hashes: dict[str, str] = {}
    for root, _, files in os.walk(scan_root):
        if any(p in root for p in SKIP_DIR_PARTS):
            continue
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix not in SUPPORTED_EXTS:
                continue
            try:
                rel = str(file_path.relative_to(scan_root))
                hashes[rel] = file_hash(file_path)
            except OSError:
                continue
    return hashes


class CodebaseIndexer:
    """Multi-repo indexer. Each chunk is tagged with `repo_id` metadata so
    cross-repo reference lookup and impact analysis work across the workspace.

    Indexing is **diff-aware and incremental**: a per-repo manifest records the
    `last_indexed_sha` and a `{relative_path: content_hash}` dict. On re-index:

      1. If `HEAD` == `last_indexed_sha` → nothing to do, skip entirely.
      2. If `last_indexed_sha` is an ancestor of `HEAD` → use `git diff` to find
         changed files; re-embed only those; delete vectors for deleted files.
      3. If the ancestor check fails (force-push / rebase) or the repo isn't git
         → fall back to a content-hash walk; re-embed only files whose hash
         differs; delete vectors for files no longer on disk.

    Unchanged files keep their existing ChromaDB vectors — no re-embedding,
    no model/API cost.
    """

    def __init__(self, workspace_root: Path, db_path: Path, repo_id: str = "default"):
        self.workspace_root = workspace_root.resolve()
        self.db_path = db_path.resolve()
        self.repo_id = repo_id

        self.client = chromadb.PersistentClient(path=str(self.db_path))

        self.chunks_collection = self.client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"},
        )
        self.imports_collection = self.client.get_or_create_collection(
            name="code_imports",
            metadata={"hnsw:space": "cosine"},
        )

    def clear_database(self):
        """Clear ALL repos from the vector store."""
        try:
            self.client.delete_collection("code_chunks")
            self.client.delete_collection("code_imports")
            self.client.delete_collection("codebase_metadata")
        except Exception:
            pass
        self.chunks_collection = self.client.get_or_create_collection(
            "code_chunks", metadata={"hnsw:space": "cosine"}
        )
        self.imports_collection = self.client.get_or_create_collection(
            "code_imports", metadata={"hnsw:space": "cosine"}
        )

    def clear_repo(self, repo_id: str | None = None):
        """Remove only the chunks for a specific repo (or current repo)."""
        rid = repo_id or self.repo_id
        for collection in (self.chunks_collection, self.imports_collection):
            try:
                results = collection.get(where={"repo_id": rid})
                if results and results.get("ids"):
                    collection.delete(ids=results["ids"])
            except Exception:
                continue

    def _delete_file_chunks(self, rel_path: str) -> None:
        """Delete all chunks + imports for a single file in the current repo."""
        where = {"$and": [{"repo_id": self.repo_id}, {"file_path": rel_path}]}
        for collection in (self.chunks_collection, self.imports_collection):
            try:
                results = collection.get(where=where)
                if results and results.get("ids"):
                    collection.delete(ids=results["ids"])
            except Exception:
                continue

    def _scan_supported_files(self, scan_root: Path) -> dict[str, str]:
        return scan_supported_files(scan_root)

    def _index_single_file(self, file_path: Path, scan_root: Path) -> tuple[int, int, dict]:
        """Chunk and embed a single file. Returns (chunk_count, import_count, style_metrics)."""
        rel_path = str(file_path.relative_to(scan_root))
        chunks = chunk_file(file_path)
        if not chunks:
            return 0, 0, {}

        # Replace existing vectors for this file (handles re-index of changed files)
        self._delete_file_chunks(rel_path)

        chunk_docs, chunk_metas, chunk_ids = [], [], []
        import_docs, import_metas, import_ids = [], [], []
        style = {"snake_case_fns": 0, "camelCase_fns": 0, "PascalCase_fns": 0,
                 "total_fns": 0, "has_docstrings": 0, "bare_excepts": 0,
                 "print_statements": 0, "logging_statements": 0}

        for idx, chunk in enumerate(chunks):
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", chunk.name)
            chunk_id = f"{self.repo_id}_{rel_path}_{chunk.chunk_type}_{safe_name}_{idx}"
            metadata = {
                "name": chunk.name,
                "type": chunk.chunk_type,
                "file_path": rel_path,
                "repo_id": self.repo_id,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
            }
            if chunk.chunk_type == "import":
                import_docs.append(chunk.content)
                import_metas.append(metadata)
                import_ids.append(chunk_id)
            else:
                chunk_docs.append(chunk.content)
                chunk_metas.append(metadata)
                chunk_ids.append(chunk_id)
                self._accumulate_style(chunk, style)

        if chunk_docs:
            self.chunks_collection.add(
                documents=chunk_docs, metadatas=chunk_metas, ids=chunk_ids
            )
        if import_docs:
            self.imports_collection.add(
                documents=import_docs, metadatas=import_metas, ids=import_ids
            )
        return len(chunk_docs), len(import_docs), style

    @staticmethod
    def _accumulate_style(chunk: CodeChunk, style: dict) -> None:
        if chunk.chunk_type == "function":
            style["total_fns"] += 1
            name = chunk.name
            if re.match(r"^[a-z_][a-z0-9_]*$", name):
                style["snake_case_fns"] += 1
            elif re.match(r"^[a-z][a-zA-Z0-9]*$", name):
                style["camelCase_fns"] += 1
            elif re.match(r"^[A-Z][a-zA-Z0-9]*$", name):
                style["PascalCase_fns"] += 1
            if '"""' in chunk.content or "'''" in chunk.content or "/**" in chunk.content:
                style["has_docstrings"] += 1
        if chunk.language == "python":
            if "except:" in chunk.content or "except Exception:" in chunk.content:
                style["bare_excepts"] += 1
            if "print(" in chunk.content:
                style["print_statements"] += 1
            if "logging." in chunk.content or "logger." in chunk.content:
                style["logging_statements"] += 1

    def _recompute_style_summary(self) -> dict:
        """Recompute aggregate style metrics from all current function chunks for this repo.

        Called after an incremental update so the style summary reflects the new
        baseline without re-reading every file's content.
        """
        metrics = {"snake_case_fns": 0, "camelCase_fns": 0, "PascalCase_fns": 0,
                   "total_fns": 0, "has_docstrings": 0, "bare_excepts": 0,
                   "print_statements": 0, "logging_statements": 0}
        try:
            results = self.chunks_collection.get(
                where={"$and": [{"repo_id": self.repo_id}, {"type": "function"}]}
            )
            for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
                chunk = CodeChunk(
                    name=meta.get("name", ""),
                    chunk_type="function",
                    content=doc,
                    start_line=int(meta.get("start_line", 0)),
                    end_line=int(meta.get("end_line", 0)),
                    file_path=meta.get("file_path", ""),
                    language=meta.get("language", "python"),
                )
                self._accumulate_style(chunk, metrics)
        except Exception:
            pass
        return metrics

    def _persist_style_summary(self, metrics: dict) -> None:
        meta_collection = self.client.get_or_create_collection("codebase_metadata")
        meta_collection.upsert(
            documents=[f"Style summary for {self.repo_id}"],
            metadatas=[{**metrics, "repo_id": self.repo_id}],
            ids=[f"style_summary_{self.repo_id}"],
        )

    def index_repo(self, repo_path: Path | None = None, incremental: bool = True) -> dict:
        """Index a repository, diff-aware and incremental when possible.

        Args:
          repo_path: Directory to index (default: workspace root). Tagged with self.repo_id.
          incremental: When True (default), use the manifest to skip unchanged
            files. When False, do a full re-index (clear + re-walk).

        Returns a summary dict with `repo_id`, `indexed_files`, `code_chunks`,
        `imports`, `style_metrics`, and a `mode` field describing which path
        was taken: `skip` | `git-incremental` | `hash-incremental` | `full`.
        """
        scan_root = (repo_path or self.workspace_root).resolve()

        # --- Full re-index path (forced or no manifest) ---
        if not incremental:
            return self._full_index(scan_root)

        manifest = load_manifest(self.db_path, self.repo_id)
        if manifest is None:
            return self._full_index(scan_root)

        last_sha = manifest.get("last_indexed_sha")
        current_sha = git_head_sha(scan_root)

        # Path 1: nothing changed (SHA equal) — skip entirely
        if last_sha and current_sha and last_sha == current_sha:
            style = self._recompute_style_summary() if self._has_style_summary() else \
                    manifest.get("stats", {}).get("style_metrics", {})
            return {
                "repo_id": self.repo_id,
                "mode": "skip",
                "indexed_files": len(manifest.get("file_hashes", {})),
                "code_chunks": manifest.get("stats", {}).get("code_chunks", 0),
                "imports": manifest.get("stats", {}).get("imports", 0),
                "style_metrics": style,
                "changed_files": 0,
            }

        # Path 2: git-native incremental (linear history)
        if last_sha and current_sha and git_is_ancestor(last_sha, current_sha, scan_root):
            return self._git_incremental_index(scan_root, last_sha, current_sha, manifest)

        # Path 3: content-hash incremental (force-push, rebase, or non-git)
        return self._hash_incremental_index(scan_root, manifest, current_sha)

    def _has_style_summary(self) -> bool:
        try:
            meta_col = self.client.get_collection("codebase_metadata")
            res = meta_col.get(ids=[f"style_summary_{self.repo_id}"])
            return bool(res and res.get("metadatas"))
        except Exception:
            return False

    def _full_index(self, scan_root: Path) -> dict:
        """Clear the repo and re-index every supported file from scratch."""
        self.clear_repo(self.repo_id)
        file_hashes = self._scan_supported_files(scan_root)
        chunk_count = 0
        import_count = 0
        style = {"snake_case_fns": 0, "camelCase_fns": 0, "PascalCase_fns": 0,
                 "total_fns": 0, "has_docstrings": 0, "bare_excepts": 0,
                 "print_statements": 0, "logging_statements": 0}
        file_count = 0

        for rel_path in sorted(file_hashes):
            file_path = scan_root / rel_path
            file_count += 1
            c, i, s = self._index_single_file(file_path, scan_root)
            chunk_count += c
            import_count += i
            for k in style:
                style[k] += s.get(k, 0)

        self._persist_style_summary(style)
        stats = {"indexed_files": file_count, "code_chunks": chunk_count,
                 "imports": import_count, "style_metrics": style}
        save_manifest(self.db_path, self.repo_id,
                      build_manifest_entry(self.repo_id, scan_root, file_hashes, stats))
        return {"repo_id": self.repo_id, "mode": "full",
                "indexed_files": file_count, "code_chunks": chunk_count,
                "imports": import_count, "style_metrics": style, "changed_files": file_count}

    def _git_incremental_index(
        self, scan_root: Path, last_sha: str, current_sha: str, manifest: dict
    ) -> dict:
        """Re-embed only files git says changed between last_sha and current_sha."""
        changes = git_changed_files(last_sha, current_sha, scan_root)
        to_embed = sorted(set(changes["added"] + changes["modified"] + changes["renamed"]))
        to_delete = sorted(set(changes["deleted"]))

        chunk_count = 0
        import_count = 0
        style_delta = {"snake_case_fns": 0, "camelCase_fns": 0, "PascalCase_fns": 0,
                       "total_fns": 0, "has_docstrings": 0, "bare_excepts": 0,
                       "print_statements": 0, "logging_statements": 0}

        for rel_path in to_embed:
            file_path = scan_root / rel_path
            if not file_path.is_file() or file_path.suffix not in SUPPORTED_EXTS:
                continue
            c, i, s = self._index_single_file(file_path, scan_root)
            chunk_count += c
            import_count += i
            for k in style_delta:
                style_delta[k] += s.get(k, 0)

        for rel_path in to_delete:
            self._delete_file_chunks(rel_path)

        # Recompute aggregate style from the full current chunk set (cheap; no re-embed)
        style = self._recompute_style_summary()
        self._persist_style_summary(style)

        # Update manifest file_hashes for the changed files
        new_hashes = dict(manifest.get("file_hashes", {}))
        for rel_path in to_embed:
            fp = scan_root / rel_path
            if fp.is_file() and fp.suffix in SUPPORTED_EXTS:
                try:
                    new_hashes[rel_path] = file_hash(fp)
                except OSError:
                    pass
        for rel_path in to_delete:
            new_hashes.pop(rel_path, None)

        stats = {"indexed_files": len(new_hashes),
                 "code_chunks": manifest.get("stats", {}).get("code_chunks", 0) + chunk_count,
                 "imports": manifest.get("stats", {}).get("imports", 0) + import_count,
                 "style_metrics": style}
        save_manifest(self.db_path, self.repo_id,
                      build_manifest_entry(self.repo_id, scan_root, new_hashes, stats))

        return {"repo_id": self.repo_id, "mode": "git-incremental",
                "indexed_files": len(new_hashes), "code_chunks": stats["code_chunks"],
                "imports": stats["imports"], "style_metrics": style,
                "changed_files": len(to_embed) + len(to_delete),
                "embedded": len(to_embed), "deleted": len(to_delete),
                "from_sha": last_sha, "to_sha": current_sha}

    def _hash_incremental_index(
        self, scan_root: Path, manifest: dict, current_sha: str | None
    ) -> dict:
        """Fallback: walk all files, compare content hashes, re-embed only changed ones.

        Used when the git ancestor check fails (force-push / rebase) or the repo
        isn't a git repo. Still incremental — unchanged files keep their vectors.
        """
        current_hashes = self._scan_supported_files(scan_root)
        d = diff_files(current_hashes, manifest)
        to_embed = sorted(set(d["added"] + d["changed"]))
        to_delete = sorted(set(d["deleted"]))

        chunk_count = 0
        import_count = 0

        for rel_path in to_embed:
            file_path = scan_root / rel_path
            c, i, _ = self._index_single_file(file_path, scan_root)
            chunk_count += c
            import_count += i

        for rel_path in to_delete:
            self._delete_file_chunks(rel_path)

        style = self._recompute_style_summary()
        self._persist_style_summary(style)

        stats = {"indexed_files": len(current_hashes),
                 "code_chunks": manifest.get("stats", {}).get("code_chunks", 0) + chunk_count,
                 "imports": manifest.get("stats", {}).get("imports", 0) + import_count,
                 "style_metrics": style}
        save_manifest(self.db_path, self.repo_id,
                      build_manifest_entry(self.repo_id, scan_root, current_hashes, stats))

        return {"repo_id": self.repo_id, "mode": "hash-incremental",
                "indexed_files": len(current_hashes), "code_chunks": stats["code_chunks"],
                "imports": stats["imports"], "style_metrics": style,
                "changed_files": len(to_embed) + len(to_delete),
                "embedded": len(to_embed), "deleted": len(to_delete),
                "to_sha": current_sha}
