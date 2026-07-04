import os
import re
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from src.utils.paths import get_workspace_root

mcp = FastMCP("FileSystemServer")

WORKSPACE_ROOT = get_workspace_root()

def _get_safe_path(path_str: str) -> Path:
    """Resolves path_str relative to WORKSPACE_ROOT and verifies it is inside WORKSPACE_ROOT."""
    # Resolve the path relative to the workspace root
    input_path = Path(path_str)
    if input_path.is_absolute():
        resolved_path = input_path.resolve()
    else:
        resolved_path = (WORKSPACE_ROOT / input_path).resolve()
        
    # Check if the resolved path is a subpath of WORKSPACE_ROOT
    if not str(resolved_path).startswith(str(WORKSPACE_ROOT)):
        raise PermissionError(f"Access denied: path '{path_str}' is outside the workspace root.")
        
    return resolved_path

@mcp.tool()
def read_file(path: str, with_line_numbers: bool = True) -> str:
    """Read the content of a file within the workspace.
    
    Args:
        path: Path to the file, absolute or relative to workspace root.
        with_line_numbers: If True, prefixes each line with its 1-indexed line number.
    """
    try:
        safe_path = _get_safe_path(path)
        if not safe_path.is_file():
            return f"Error: '{path}' is not a file."
            
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            
        if not with_line_numbers:
            return content
            
        lines = content.splitlines()
        numbered_lines = [f"{i+1}: {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered_lines)
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def list_directory(path: str = ".", recursive: bool = False) -> str:
    """List contents of a directory.
    
    Args:
        path: Path to list, relative to workspace root. Defaults to '.' (workspace root).
        recursive: If True, lists all files recursively.
    """
    try:
        safe_path = _get_safe_path(path)
        if not safe_path.is_dir():
            return f"Error: '{path}' is not a directory."
            
        result = []
        if recursive:
            for root, _, files in os.walk(safe_path):
                # Check for virtual environment folder and git to skip heavy files
                if ".venv" in root or ".git" in root or "__pycache__" in root:
                    continue
                root_path = Path(root)
                rel_root = root_path.relative_to(WORKSPACE_ROOT)
                for file in files:
                    result.append(str(rel_root / file))
        else:
            for item in safe_path.iterdir():
                if item.name in [".venv", ".git", "__pycache__", ".DS_Store"]:
                    continue
                rel_item = item.relative_to(WORKSPACE_ROOT)
                type_str = "[DIR]" if item.is_dir() else "[FILE]"
                result.append(f"{type_str} {rel_item}")
                
        return "\n".join(result) if result else "Directory is empty or skipped files only."
    except Exception as e:
        return f"Error listing directory: {str(e)}"

@mcp.tool()
def search_files(pattern: str, path: str = ".", extension_filter: str = "") -> str:
    """Search for a regex pattern within files in the workspace (like grep).
    
    Args:
        pattern: The regex pattern to search for.
        path: Directory to search inside, relative to workspace root. Defaults to '.' (workspace root).
        extension_filter: Optional comma-separated extensions (e.g. '.py,.ts') to filter search targets.
    """
    try:
        safe_path = _get_safe_path(path)
        if not safe_path.is_dir():
            return f"Error: '{path}' is not a directory."
            
        compiled_regex = re.compile(pattern)
        extensions = [ext.strip() for ext in extension_filter.split(",")] if extension_filter else []
        
        matches = []
        for root, _, files in os.walk(safe_path):
            if ".venv" in root or ".git" in root or "__pycache__" in root:
                continue
            for file in files:
                file_path = Path(root) / file
                
                # Apply extension filter if defined
                if extensions and not any(file.endswith(ext) for ext in extensions):
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        for line_num, line in enumerate(f, 1):
                            if compiled_regex.search(line):
                                rel_path = file_path.relative_to(WORKSPACE_ROOT)
                                matches.append(f"{rel_path}:{line_num}: {line.strip()}")
                except Exception:
                    # Skip unreadable or binary files silently
                    continue
                    
        return "\n".join(matches) if matches else f"No matches found for pattern '{pattern}'."
    except Exception as e:
        return f"Error searching files: {str(e)}"

@mcp.tool()
def get_file_metadata(path: str) -> str:
    """Get metadata of a file or directory (size, extension, modifications)."""
    try:
        safe_path = _get_safe_path(path)
        if not safe_path.exists():
            return f"Error: '{path}' does not exist."
            
        stats = safe_path.stat()
        file_type = "Directory" if safe_path.is_dir() else "File"
        size = stats.st_size
        modified = stats.st_mtime
        
        metadata = [
            f"Type: {file_type}",
            f"Absolute Path: {safe_path}",
            f"Size: {size} bytes",
            f"Last Modified Timestamp: {modified}"
        ]
        
        if safe_path.is_file():
            metadata.append(f"Extension: {safe_path.suffix}")
            
        return "\n".join(metadata)
    except Exception as e:
        return f"Error getting metadata: {str(e)}"

if __name__ == "__main__":
    mcp.run()
