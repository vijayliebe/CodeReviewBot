import os
import re
from pathlib import Path

def profile_style(file_paths: list[Path]) -> dict:
    """Analyze naming conventions, comments, and style patterns of listed files.
    Returns style metrics.
    """
    snake_case_pat = re.compile(r'^[a-z_][a-z0-9_]*$')
    camel_case_pat = re.compile(r'^[a-z][a-zA-Z0-9]*$')
    pascal_case_pat = re.compile(r'^[A-Z][a-zA-Z0-9]*$')
    
    metrics = {
        "function_count": 0,
        "snake_case_fns": 0,
        "camelCase_fns": 0,
        "PascalCase_fns": 0,
        "class_count": 0,
        "PascalCase_classes": 0,
        "comment_lines": 0,
        "code_lines": 0,
        "docstrings": 0
    }
    
    for path in file_paths:
        if not path.is_file():
            continue
            
        ext = path.suffix.lower()
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue
            
        lines = content.splitlines()
        metrics["code_lines"] += len(lines)
        
        # Check comments and docstrings
        in_docstring = False
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
                
            # Count comments
            if ext == ".py" and line_str.startswith("#"):
                metrics["comment_lines"] += 1
            elif ext in [".js", ".ts", ".jsx", ".tsx", ".java", ".go"] and (line_str.startswith("//") or line_str.startswith("/*") or line_str.startswith("*")):
                metrics["comment_lines"] += 1
                
            # Basic docstring tracker
            if ext == ".py":
                if '"""' in line_str or "'''" in line_str:
                    if line_str.count('"""') == 2 or line_str.count("'''") == 2:
                        metrics["docstrings"] += 1
                    else:
                        in_docstring = not in_docstring
                        if in_docstring:
                            metrics["docstrings"] += 1
            elif ext in [".js", ".ts", ".java"]:
                if "/**" in line_str:
                    in_docstring = True
                    metrics["docstrings"] += 1
                elif "*/" in line_str:
                    in_docstring = False
                    
        # Match function and class declarations depending on language
        if ext == ".py":
            # Find python classes: class ClassName:
            classes = re.findall(r'^\s*class\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
            metrics["class_count"] += len(classes)
            for c in classes:
                if pascal_case_pat.match(c):
                    metrics["PascalCase_classes"] += 1
                    
            # Find python functions: def function_name(...):
            funcs = re.findall(r'^\s*def\s+([a-zA-Z0-9_]+)\s*\(', content, re.MULTILINE)
            metrics["function_count"] += len(funcs)
            for f in funcs:
                if snake_case_pat.match(f):
                    metrics["snake_case_fns"] += 1
                elif camel_case_pat.match(f):
                    metrics["camelCase_fns"] += 1
                elif pascal_case_pat.match(f):
                    metrics["PascalCase_fns"] += 1
                    
        elif ext in [".js", ".ts", ".jsx", ".tsx"]:
            # Find classes
            classes = re.findall(r'^\s*class\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
            metrics["class_count"] += len(classes)
            for c in classes:
                if pascal_case_pat.match(c):
                    metrics["PascalCase_classes"] += 1
                    
            # Find functions: function name(), const name = () =>
            funcs1 = re.findall(r'^\s*(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(', content, re.MULTILINE)
            funcs2 = re.findall(r'^\s*(?:const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\(.*?\)\s*=>', content, re.MULTILINE)
            all_fns = funcs1 + funcs2
            metrics["function_count"] += len(all_fns)
            for f in all_fns:
                if snake_case_pat.match(f):
                    metrics["snake_case_fns"] += 1
                elif camel_case_pat.match(f):
                    metrics["camelCase_fns"] += 1
                elif pascal_case_pat.match(f):
                    metrics["PascalCase_fns"] += 1
                    
    return metrics
