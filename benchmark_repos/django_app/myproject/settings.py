DEBUG = True
SECRET_KEY = "django-insecure-hardcoded-key-1234567890abcdef"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]

# VIOLATION (no-print-statements): print in production settings
print("Django settings loaded for dev")
