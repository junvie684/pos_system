from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from . import throttle  # noqa: F401  connects the sign-in throttle signals
