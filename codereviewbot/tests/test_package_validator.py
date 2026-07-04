"""Tests for package validator — PyPI and npm hallucination detection."""

from unittest.mock import patch, MagicMock

from src.utils.package_validator import validate_python_package, validate_npm_package


def test_pypi_known_package():
    """A real package like 'requests' should return True."""
    with patch("src.utils.package_validator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert validate_python_package("requests") is True


def test_pypi_hallucinated_package():
    """A fake package should return False (404)."""
    with patch("src.utils.package_validator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        assert validate_python_package("py_fake_cryptography_pkg") is False


def test_pypi_stdlib_returns_true():
    """Standard library modules should return True without network call."""
    with patch("src.utils.package_validator.requests.get") as mock_get:
        assert validate_python_package("os") is True
        assert validate_python_package("sys") is True
        mock_get.assert_not_called()


def test_pypi_offline_returns_true():
    """Network failure should default to True (avoid false positives)."""
    with patch("src.utils.package_validator.requests.get", side_effect=Exception("timeout")):
        assert validate_python_package("somepkg") is True


def test_npm_known_package():
    with patch("src.utils.package_validator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert validate_npm_package("react") is True


def test_npm_hallucinated_package():
    with patch("src.utils.package_validator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        assert validate_npm_package("nonexistent-fake-pkg-xyz") is False


def test_npm_scoped_package():
    """Scoped packages like @types/node should be URL-encoded correctly."""
    with patch("src.utils.package_validator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert validate_npm_package("@types/node") is True
        # Verify URL was constructed with encoded slash
        called_url = mock_get.call_args[0][0]
        assert "%2F" in called_url
