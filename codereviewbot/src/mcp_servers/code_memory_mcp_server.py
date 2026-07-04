import os
import re
from pathlib import Path
import chromadb
from mcp.server.fastmcp import FastMCP
from src.memory.indexer import CodebaseIndexer
from src.utils.paths import get_workspace_root
from src.workspace.store import workspace_chroma_path, find_repo_id_for_path

mcp = FastMCP("CodeMemoryServer")

WORKSPACE_ROOT = get_workspace_root()
DB_PATH = workspace_chroma_path(WORKSPACE_ROOT)


def _resolve_repo_id(repo_hint: str | None = None) -> str:
    """Determine which repo_id to operate on."""
    if repo_hint:
        return repo_hint
    return "default"


def _get_indexer(repo_id: str = "default") -> CodebaseIndexer:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return CodebaseIndexer(WORKSPACE_ROOT, DB_PATH, repo_id=repo_id)


@mcp.tool()
def index_codebase(repo_path: str = "", repo_id: str = "") -> str:
    """Index a repository into the shared vector store.

    Args:
        repo_path: Path to the repo to index. If empty, indexes the workspace root.
        repo_id: Identifier for this repo within the workspace. Defaults to 'default'.
                 When set, chunks are tagged with this repo_id for cross-repo queries.
    """
    try:
        rid = repo_id or "default"
        rpath = Path(repo_path) if repo_path else WORKSPACE_ROOT
        indexer = _get_indexer(rid)
        summary = indexer.index_repo(rpath)

        style = summary.get("style_metrics", {})
        return (
            f"Indexed repo '{summary['repo_id']}' at {rpath}\n"
            f"- Files: {summary['indexed_files']}\n"
            f"- Code chunks: {summary['code_chunks']}\n"
            f"- Imports: {summary['imports']}\n"
            f"Style: snake={style.get('snake_case_fns', 0)} camel={style.get('camelCase_fns', 0)} "
            f"pascal={style.get('PascalCase_fns', 0)} total_fns={style.get('total_fns', 0)}"
        )
    except Exception as e:
        return f"Error indexing codebase: {e}"


@mcp.tool()
def search_similar_code(query_text: str, n_results: int = 5, repo_id: str = "") -> str:
    """Semantic similarity search across indexed code. Filters by repo_id when given.

    `n_results` is capped at 5 to keep the LLM payload small (token budget).
    """
    try:
        rid = _resolve_repo_id(repo_id)
        indexer = _get_indexer(rid)
        # Cap n_results to protect token budget — callers rarely need more than 5.
        n_results = max(1, min(int(n_results), 5))
        kwargs = {"query_texts": [query_text], "n_results": n_results}
        if repo_id:
            kwargs["where"] = {"repo_id": repo_id}
        results = indexer.chunks_collection.query(**kwargs)

        output = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            dists = results["distances"][0] if "distances" in results else [0] * len(docs)
            for doc, meta, dist in zip(docs, metas, dists):
                sim = 1 - dist
                repo_tag = f" [{meta.get('repo_id', '?')}]" if meta.get("repo_id") else ""
                output.append(
                    f"=== {meta['file_path']}{repo_tag} (Type: {meta['type']}, "
                    f"Lines: {meta['start_line']}-{meta['end_line']}, Sim: {sim:.2f}) ===\n{doc}\n"
                )
        return "\n".join(output) if output else "No similar code found."
    except Exception as e:
        return f"Error searching code memory: {e}"


@mcp.tool()
def get_style_profile(repo_id: str = "") -> str:
    """Retrieve style metrics for a repo (or the default repo)."""
    try:
        indexer = _get_indexer(_resolve_repo_id(repo_id))
        meta_col = indexer.client.get_collection("codebase_metadata")
        rid = repo_id or "default"
        results = meta_col.get(ids=[f"style_summary_{rid}"])

        if results and results.get("metadatas"):
            style = results["metadatas"][0]
            total = style.get("total_fns", 0)
            snake = style.get("snake_case_fns", 0)
            camel = style.get("camelCase_fns", 0)
            pascal = style.get("PascalCase_fns", 0)
            dominant = "none"
            if total > 0:
                dominant = max([("snake_case", snake), ("camelCase", camel), ("PascalCase", pascal)], key=lambda x: x[1])[0]
            return (
                f"repo: {rid}\n"
                f"dominant_style: {dominant}\n"
                f"snake_case: {snake} | camelCase: {camel} | PascalCase: {pascal} | total: {total}\n"
                f"docstrings: {style.get('has_docstrings', 0)}/{total}\n"
                f"bare_excepts: {style.get('bare_excepts', 0)}\n"
                f"print_count: {style.get('print_statements', 0)}\n"
                f"logging_count: {style.get('logging_statements', 0)}"
            )
        return f"Style profile not found for repo '{rid}'. Run index_codebase first."
    except Exception as e:
        return f"Error retrieving style profile: {e}"


@mcp.tool()
def find_references(symbol_name: str, repo_id: str = "", max_results: int = 25) -> str:
    """Find all references to a symbol. When repo_id is given, searches only that repo;
    otherwise searches ALL indexed repos (cross-repo reference lookup).

    `max_results` caps the returned reference count to protect the LLM token budget
    (default 25, hard cap 50). The full list is rarely useful to the LLM and large
    reference sets blow up the input size.
    """
    try:
        rid = _resolve_repo_id(repo_id)
        indexer = _get_indexer(rid)
        max_results = max(1, min(int(max_results), 50))
        kwargs = {"query_texts": [symbol_name], "n_results": 30}
        if repo_id:
            kwargs["where"] = {"repo_id": repo_id}
        results = indexer.chunks_collection.query(**kwargs)

        references = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            for doc, meta in zip(docs, metas):
                lines = doc.splitlines()
                for i, line in enumerate(lines):
                    if re.search(r"\b" + re.escape(symbol_name) + r"\b", line):
                        if meta["type"] == "function" and _is_definition(line, symbol_name):
                            continue
                        line_num = int(meta["start_line"]) + i
                        repo_tag = f" [{meta.get('repo_id', '?')}]" if meta.get("repo_id") else ""
                        references.append(f"{meta['file_path']}{repo_tag}:{line_num}: {line.strip()}")
                        if len(references) >= max_results:
                            break
                if len(references) >= max_results:
                    break
        if not references:
            return f"No references found for '{symbol_name}'."
        suffix = f"\n... ({len(references)} shown, capped at {max_results} for token budget)"
        return "\n".join(references) + suffix
    except Exception as e:
        return f"Error finding references: {e}"


def _is_definition(line: str, symbol_name: str) -> bool:
    line = line.strip()
    return (
        line.startswith(f"def {symbol_name}")
        or line.startswith(f"class {symbol_name}")
        or line.startswith(f"function {symbol_name}")
        or f"const {symbol_name} = " in line
    )


@mcp.tool()
def get_dependency_graph(repo_id: str = "", max_edges: int = 50) -> str:
    """Return import graph. Filters by repo_id when given.

    `max_edges` caps the returned edge count to protect the LLM token budget
    (default 50, hard cap 200). Large import graphs are rarely fully consumed
    by the LLM and dominate the input size.
    """
    try:
        rid = _resolve_repo_id(repo_id)
        indexer = _get_indexer(rid)
        max_edges = max(1, min(int(max_edges), 200))
        kwargs = {}
        if repo_id:
            kwargs["where"] = {"repo_id": repo_id}
        results = indexer.imports_collection.get(**kwargs)

        graph = []
        if results and results.get("documents"):
            docs = results["documents"]
            metas = results["metadatas"]
            for doc, meta in zip(docs, metas):
                repo_tag = f" [{meta.get('repo_id', '?')}]" if meta.get("repo_id") else ""
                graph.append(f"{meta['file_path']}{repo_tag} -> {doc.strip()}")
                if len(graph) >= max_edges:
                    break
        if not graph:
            return "No imports indexed."
        suffix = f"\n... ({len(graph)} edges shown, capped at {max_edges} for token budget)"
        return "\n".join(graph) + suffix
    except Exception as e:
        return f"Error building dependency graph: {e}"


@mcp.tool()
def get_pattern_frequency(pattern: str, repo_id: str = "") -> str:
    """Calculate frequency of a code pattern across the codebase (or a single repo)."""
    try:
        indexer = _get_indexer(_resolve_repo_id(repo_id))
        kwargs = {}
        if repo_id:
            kwargs["where"] = {"repo_id": repo_id}
        results = indexer.chunks_collection.get(**kwargs)

        if not results or not results.get("documents"):
            return "0.0 (No chunks indexed)"
        total = len(results["documents"])
        matches = sum(1 for doc in results["documents"] if pattern in doc)
        freq = matches / total if total > 0 else 0
        return f"Frequency: {freq:.4f} ({matches} matches out of {total} chunks)"
    except Exception as e:
        return f"Error calculating pattern frequency: {e}"


if __name__ == "__main__":
    mcp.run()
