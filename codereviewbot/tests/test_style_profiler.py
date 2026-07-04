"""Tests for the style profiler — naming convention detection and metrics."""

from pathlib import Path

from src.memory.style_profiler import profile_style


def test_style_profiler_python_snake_case(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("def process_payment():\n    return 1\ndef validate_user():\n    return True\n")
    metrics = profile_style([f])
    assert metrics["function_count"] == 2
    assert metrics["snake_case_fns"] == 2
    assert metrics["camelCase_fns"] == 0


def test_style_profiler_mixed_naming(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("def processData():\n    return 1\ndef clean_data():\n    return True\n")
    metrics = profile_style([f])
    assert metrics["function_count"] == 2
    assert metrics["snake_case_fns"] == 1
    assert metrics["camelCase_fns"] == 1


def test_style_profiler_js_functions(tmp_path):
    f = tmp_path / "app.js"
    f.write_text("function fetchData() { return 1; }\nconst processData = () => 2;\n")
    metrics = profile_style([f])
    assert metrics["function_count"] == 2
    assert metrics["camelCase_fns"] >= 1


def test_style_profiler_pascal_classes(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("class PaymentHandler:\n    pass\nclass UserAccount:\n    pass\n")
    metrics = profile_style([f])
    assert metrics["class_count"] == 2
    assert metrics["PascalCase_classes"] == 2


def test_style_profiler_docstrings(tmp_path):
    f = tmp_path / "app.py"
    f.write_text('def foo():\n    """Does something."""\n    return 1\n')
    metrics = profile_style([f])
    assert metrics["docstrings"] >= 1


def test_style_profiler_empty_file(tmp_path):
    f = tmp_path / "empty.py"
    f.write_text("")
    metrics = profile_style([f])
    assert metrics["function_count"] == 0


def test_style_profiler_nonexistent_file(tmp_path):
    metrics = profile_style([tmp_path / "doesnotexist.py"])
    assert metrics["function_count"] == 0
