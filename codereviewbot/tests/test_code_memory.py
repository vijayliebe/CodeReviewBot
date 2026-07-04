import os
import shutil
import tempfile
from pathlib import Path
from src.memory.code_chunker import chunk_file
from src.memory.indexer import CodebaseIndexer

def test_code_chunker(tmp_path):
    # Create a mock Python file
    py_content = """
import os
from decimal import Decimal

class UserPayment:
    def __init__(self, user_id):
        self.user_id = user_id

    def process(self, amount):
        print("Processing payment")
        return True
"""
    file_path = tmp_path / "mock_payment.py"
    file_path.write_text(py_content)
    
    chunks = chunk_file(file_path)
    
    # Assert import chunk, class chunk, and method chunk exist
    chunk_types = [c.chunk_type for c in chunks]
    assert "import" in chunk_types
    assert "class" in chunk_types
    assert "function" in chunk_types
    
    # Verify name matching
    class_chunk = next(c for c in chunks if c.chunk_type == "class")
    assert class_chunk.name == "UserPayment"
    
    func_chunk = next(c for c in chunks if c.chunk_type == "function" and c.name == "process")
    assert func_chunk.name == "process"

def test_indexer(tmp_path):
    # Setup temporary directories for workspace and ChromaDB
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    
    # Write python file in workspace
    (workspace_dir / "app.py").write_text("def hello_world():\n    return 'Hello'\n")
    
    db_dir = tmp_path / "chroma_db"
    
    # Run Indexer
    indexer = CodebaseIndexer(workspace_dir, db_dir)
    summary = indexer.index_repo()
    
    assert summary["indexed_files"] == 1
    assert summary["code_chunks"] == 1
    
    # Verify metadata contains style profile
    style = summary["style_metrics"]
    assert style["total_fns"] == 1
    assert style["snake_case_fns"] == 1
