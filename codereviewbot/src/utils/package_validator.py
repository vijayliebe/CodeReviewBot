import requests

def validate_python_package(package_name: str) -> bool:
    """Checks if a python package exists on PyPI. Returns True if it exists or if check fails, 
    False if it returns 404 (does not exist).
    """
    # Clean package name (remove submodules or versions)
    package_name = package_name.split('.')[0].strip()
    if not package_name or package_name in ["os", "sys", "re", "json", "math", "collections", "datetime", "pathlib", "ast"]:
        return True # Standard library
        
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 404:
            return False
        return True
    except Exception:
        # Fallback to True if offline or timeout to prevent false positives
        return True

def validate_npm_package(package_name: str) -> bool:
    """Checks if a JS/TS package exists in the npm registry."""
    if not package_name or package_name.startswith('.'):
        return True # Local import
        
    # Handle scoped packages e.g. @types/node
    url_name = package_name
    if package_name.startswith('@') and '/' in package_name:
        parts = package_name.split('/')
        url_name = f"{parts[0]}%2F{parts[1]}"
        
    url = f"https://registry.npmjs.org/{url_name}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 404:
            return False
        return True
    except Exception:
        return True
