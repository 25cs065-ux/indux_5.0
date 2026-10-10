# admin-app/__init__.py
# Makes admin-app importable as a package when sys.path includes the parent dir.
# Note: Python package names cannot contain hyphens; we use the directory
# directly via sys.path manipulation in both main.py and tests.
