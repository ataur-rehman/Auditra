"""Creates the first admin and compliance officer accounts if they do not exist yet.

Passwords come from ADMIN_PASSWORD and OFFICER_PASSWORD. The built-in development passwords are only accepted
while DEBUG is on, so a public deployment never starts with a password that is written in the repository.

Existing accounts keep the password they have (it may have been changed in the console). Set
RESET_DEFAULT_PASSWORDS=true for one deploy to set both accounts back to the variables, for example after losing
the admin password; remove the variable again afterwards.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from compliance.models import AuditraUser

DEV_PASSWORDS = {'admin': 'Admin@2026', 'compliance_officer': 'Auditra@2026'}
ACCOUNTS = [
    ('admin', 'ADMIN_PASSWORD', 'admin', 'admin@auditra.com'),
    ('compliance_officer', 'OFFICER_PASSWORD', 'compliance_officer', 'compliance@auditra.com'),
]


class Command(BaseCommand):
    help = 'Create the admin and compliance officer logins (passwords from ADMIN_PASSWORD / OFFICER_PASSWORD).'

    def _password(self, env_name, username):
        # Values pasted into a hosting dashboard often carry a stray newline or \r; the login form trims them.
        password = os.getenv(env_name, '').strip()
        if not password:
            if not settings.DEBUG:
                raise CommandError(f'Set {env_name} to create the {username} account when DEBUG is off.')
            password = DEV_PASSWORDS[username]
        elif not settings.DEBUG and password == DEV_PASSWORDS[username]:
            raise CommandError(f'{env_name} must not be the development password when DEBUG is off.')
        return password

    def handle(self, *args, **kwargs):
        reset = os.getenv('RESET_DEFAULT_PASSWORDS', '').strip().lower() in ('1', 'true', 'yes')
        for username, env_name, role, email in ACCOUNTS:
            user = AuditraUser.objects.filter(username=username).first()
            if user is None:
                user = AuditraUser(username=username, email=email, role=role,
                                   is_staff=role == 'admin', is_superuser=role == 'admin')
                user.set_password(self._password(env_name, username))
                user.save()
                self.stdout.write(f'{username} created.')
            elif reset:
                user.set_password(self._password(env_name, username))
                user.is_active = True
                user.save()
                self.stdout.write(f'{username} password reset from {env_name}.')
