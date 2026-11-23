"""
Make sure the pos_archive database exists and is migrated.

On Postgres, when the archive lives on the same server as the main database
(no ARCHIVE_DATABASE_URL), the database is created if it's missing. A separate
archive server must already have its database. Then the archive app's
migrations run against it. Safe to run on every deploy.
"""
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = 'Create (if needed) and migrate the pos_archive database.'

    def handle(self, *args, **options):
        archive = settings.DATABASES['archive']
        if 'postgresql' in archive['ENGINE'] and not os.environ.get('ARCHIVE_DATABASE_URL'):
            name = archive['NAME']
            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [name])
                if cursor.fetchone() is None:
                    cursor.execute('SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user')
                    if not cursor.fetchone()[0]:
                        user = connections['default'].settings_dict['USER']
                        raise CommandError(
                            f'Database "{name}" does not exist and user "{user}" is not allowed to '
                            f'create databases. Create it once as a Postgres admin:\n'
                            f'  CREATE DATABASE {name} OWNER {user};\n'
                            f'then run this command again.'
                        )
                    # Identifiers can't be query parameters; the name comes from settings.
                    cursor.execute(f'CREATE DATABASE "{name}"')
                    self.stdout.write(f'Created database {name}.')
        call_command('migrate', database='archive', interactive=False, verbosity=1)
        self.stdout.write(self.style.SUCCESS('Archive database is ready.'))
