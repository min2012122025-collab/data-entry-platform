"""Process-wide application services shared by API routers and startup checks."""

from .core.config import settings
from .db.database import Database
from .services.import_service import ImportService


settings.validate_process_environment()
database = Database()
service = ImportService(database, settings.upload_dir, source_dir=settings.source_dir)

__all__ = ["database", "service"]
