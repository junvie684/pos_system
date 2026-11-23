"""Send the archive app's tables to the 'archive' database and nothing else."""

ARCHIVE_DB = 'archive'
ARCHIVE_APP = 'archive'


class ArchiveRouter:
    def _db(self, model):
        return ARCHIVE_DB if model._meta.app_label == ARCHIVE_APP else None

    def db_for_read(self, model, **hints):
        return self._db(model)

    def db_for_write(self, model, **hints):
        return self._db(model)

    def allow_relation(self, obj1, obj2, **hints):
        # Rows in different databases can't reference each other.
        in_archive = {obj._meta.app_label == ARCHIVE_APP for obj in (obj1, obj2)}
        return len(in_archive) == 1

    def allow_migrate(self, db, app_label, **hints):
        if app_label == ARCHIVE_APP:
            return db == ARCHIVE_DB
        return db != ARCHIVE_DB
