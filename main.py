"""Vercel FastAPI entrypoint for Word Hunt.

Keep the app in api/index.py as the single source of truth so the root
FastAPI entrypoint and the API function cannot drift apart.
"""
from api.index import app
