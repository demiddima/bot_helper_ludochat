# services/db_api_client.py
# shim-слой для обратной совместимости импортов:
# from services.db_api_client import db_api_client / DBApiClient
from __future__ import annotations
from .db_api import DBApiClient, db_api_client

__all__ = ["DBApiClient", "db_api_client"]