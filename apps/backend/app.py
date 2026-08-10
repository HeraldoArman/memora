"""Root app entry — exposes `app` for `uvicorn app:app --app-dir apps/backend`."""

from api.app import create_app

app = create_app()
