import ast
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass
class CodeChunk:
    name: str
    chunk_type: str  # "class" | "function" | "import" | "module"
    content: str
    start_line: int
    end_line: int
    file_path: str
    language: str

class PythonASTParser(ast.NodeVisitor):
    """AST visitor to extract classes, functions, and imports from Python code."""
    def __init__(self, content: str, file_path: str):
        self.content = content
        self.file_path = file_path
        self.lines = content.splitlines()
        self.chunks = []
        
    def _get_source_segment(self, start_line: int, end_line: int) -> str:
        # ast lines are 1-indexed
        segment_lines = self.lines[start_line-1:end_line]
        return "\n".join(segment_lines)

    def visit_ClassDef(self, node: ast.ClassDef):
        # Determine node end line (supported in modern Python, fallback if needed)
        end_line = getattr(node, "end_lineno", node.lineno)
        content = self._get_source_segment(node.lineno, end_line)
        self.chunks.append(CodeChunk(
            name=node.name,
            chunk_type="class",
            content=content,
            start_line=node.lineno,
            end_line=end_line,
            file_path=self.file_path,
            language="python"
        ))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # We only want to capture top-level functions or class methods, not nested helper functions
        end_line = getattr(node, "end_lineno", node.lineno)
        content = self._get_source_segment(node.lineno, end_line)
        
        # Determine if it's a method or standalone function
        chunk_type = "function"
        self.chunks.append(CodeChunk(
            name=node.name,
            chunk_type=chunk_type,
            content=content,
            start_line=node.lineno,
            end_line=end_line,
            file_path=self.file_path,
            language="python"
        ))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        end_line = getattr(node, "end_lineno", node.lineno)
        content = self._get_source_segment(node.lineno, end_line)
        self.chunks.append(CodeChunk(
            name=node.name,
            chunk_type="function",
            content=content,
            start_line=node.lineno,
            end_line=end_line,
            file_path=self.file_path,
            language="python"
        ))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        names = [alias.name for alias in node.names]
        content = self._get_source_segment(node.lineno, node.lineno)
        self.chunks.append(CodeChunk(
            name=", ".join(names),
            chunk_type="import",
            content=content,
            start_line=node.lineno,
            end_line=node.lineno,
            file_path=self.file_path,
            language="python"
        ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        names = [alias.name for alias in node.names]
        content = self._get_source_segment(node.lineno, node.lineno)
        self.chunks.append(CodeChunk(
            name=f"{module}: {', '.join(names)}",
            chunk_type="import",
            content=content,
            start_line=node.lineno,
            end_line=node.lineno,
            file_path=self.file_path,
            language="python"
        ))

def chunk_python_file(content: str, file_path: str) -> list[CodeChunk]:
    """Parse Python file using AST and return chunks."""
    try:
        tree = ast.parse(content, filename=file_path)
        parser = PythonASTParser(content, file_path)
        parser.visit(tree)
        return parser.chunks
    except SyntaxError:
        # Fallback to regex if syntax error (e.g. invalid python or template python)
        return chunk_generic_regex(content, file_path, "python")

def chunk_generic_regex(content: str, file_path: str, language: str) -> list[CodeChunk]:
    """Fallback regex-based chunker for multiple languages (JS, TS, Java, Python, Go, etc.)."""
    lines = content.splitlines()
    chunks = []
    
    # 1. Look for function/method declarations
    # Matches common patterns like: function name(args), const name = (args) =>, def name(args), public void name(args)
    fn_patterns = [
        # Python: def name(args):
        (r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", "function"),
        # JS/TS: function name(args), async function name(args)
        (r"^\s*(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", "function"),
        # JS/TS: const name = async (args) =>
        (r"^\s*(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s*)?\(.*?\)\s*=>", "function"),
        # JS/TS class method: name(args) {
        (r"^\s*(?:async\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*?\)\s*\{", "function"),
        # Java/C#: public/private/static void/Type name(args)
        (r"^\s*(?:public|private|protected|static|final|native|synchronized|abstract)\s+[\w<>]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", "function"),
        # Go: func name(args) or func (receiver) name(args)
        (r"^\s*func\s+(?:\(.*?\)\s*)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", "function"),
        # Class definitions (Python, JS, TS, Java, C++)
        (r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)", "class"),
        # Interface/Type definitions
        (r"^\s*(?:interface|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)", "class")
    ]
    
    # 2. Look for imports/requires
    import_patterns = [
        # Python: import x, from x import y
        r"^\s*(?:import\s+\w+|from\s+[\w\.]+\s+import)",
        # JS/TS: import x from 'y', import { x } from 'y', require('y')
        r"^\s*(?:import\s+.*?from\s+['\"].*?['\"]|const\s+.*?=\s*require\(.*?\))",
        # Java: import x.y.z;
        r"^\s*import\s+[\w\.\*]+;"
    ]
    
    # Find functions/classes
    for i, line in enumerate(lines):
        line_num = i + 1
        
        # Check imports
        is_import = False
        for pattern in import_patterns:
            if re.search(pattern, line):
                chunks.append(CodeChunk(
                    name=line.strip(),
                    chunk_type="import",
                    content=line.strip(),
                    start_line=line_num,
                    end_line=line_num,
                    file_path=file_path,
                    language=language
                ))
                is_import = True
                break
                
        if is_import:
            continue
            
        # Check function/class declarations
        for pattern, chunk_type in fn_patterns:
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                
                # Approximate the end of the block by matching braces or indentation
                # For brace languages (JS, TS, Java, Go, etc.), we look for matching '{' and '}'
                end_line = line_num
                if "{" in line or (line_num < len(lines) and "{" in lines[line_num]):
                    brace_count = 0
                    started = False
                    for j in range(i, len(lines)):
                        started = started or "{" in lines[j]
                        brace_count += lines[j].count("{")
                        brace_count -= lines[j].count("}")
                        if started and brace_count <= 0:
                            end_line = j + 1
                            break
                    if end_line == line_num: # fallback if brace matching failed
                        end_line = min(line_num + 30, len(lines))
                # For indentation languages (Python), we look for the next line with <= indentation
                elif language == "python":
                    indent = len(line) - len(line.lstrip())
                    for j in range(i + 1, len(lines)):
                        stripped = lines[j].strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        next_indent = len(lines[j]) - len(lines[j].lstrip())
                        if next_indent <= indent:
                            end_line = j
                            break
                    if end_line == line_num: # fallback
                        end_line = min(line_num + 20, len(lines))
                else:
                    # Generic fallback: just take next 20 lines
                    end_line = min(line_num + 20, len(lines))
                    
                content_segment = "\n".join(lines[line_num-1:end_line])
                chunks.append(CodeChunk(
                    name=name,
                    chunk_type=chunk_type,
                    content=content_segment,
                    start_line=line_num,
                    end_line=end_line,
                    file_path=file_path,
                    language=language
                ))
                break
                
    return chunks

def chunk_file(file_path: Path) -> list[CodeChunk]:
    """Detects file type, reads content, and returns chunks."""
    if not file_path.is_file():
        return []
        
    ext = file_path.suffix.lower()
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".swift": "swift",
        ".kt": "kotlin",
        ".dart": "dart",
        ".java": "java",
        ".go": "go",
        ".tf": "terraform",
        ".tfvars": "terraform",
        ".sh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml"
    }
    
    language = lang_map.get(ext, "text")
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            
        if not content.strip():
            return []
            
        # Call specific parsers
        if language == "python":
            return chunk_python_file(content, str(file_path))
        else:
            return chunk_generic_regex(content, str(file_path), language)
            
    except Exception:
        # Fail silently and return empty chunks for unreadable files
        return []
