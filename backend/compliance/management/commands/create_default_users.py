"""Creates the first admin and compliance officer accounts if they do not exist yet.

Passwords come from ADMIN_PASSWORD and OFFICER_PASSWORD. The built-in development passwords are only accepted
while DEBUG is on, so a public deployment never starts with a password that is written in the repository.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from compliance.models import AuditraUser

DEV_PASSWORDS = {'admin': 'Admin@2026', 'compliance_officer': 'Auditra@2026'}


class Command(BaseCommand):
    help = 'Create the admin and compliance officer logins (passwords from ADMIN_PASSWORD / OFFICER_PASSWORD).'

    def _password(self, env_name, username):
        password = os.getenv(env_name, '')
        if not password:
            if not settings.DEBUG:
                raise CommandError(f'Set {env_name} to create the {username} account when DEBUG is off.')
            password = DEV_PASSWORDS[username]
        elif not settings.DEBUG and password == DEV_PASSWORDS[username]:
            raise CommandError(f'{env_name} must not be the development password when DEBUG is off.')
        return password

    def handle(self, *args, **kwargs):
        if not AuditraUser.objects.filter(username='admin').exists():
            AuditraUser.objects.create_superuser(
                username='admin', email='admin@auditra.com',
                password=self._password('ADMIN_PASSWORD', 'admin'), role='admin',
            )
            self.stdout.write('Admin created.')

        if not AuditraUser.objects.filter(username='compliance_officer').exists():
            user = AuditraUser(username='compliance_officer', email='compliance@auditra.com', role='compliance_officer')
            user.set_password(self._password('OFFICER_PASSWORD', 'compliance_officer'))
            user.save()
            self.stdout.write('Compliance officer created.')
