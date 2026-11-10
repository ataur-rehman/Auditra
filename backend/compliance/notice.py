"""The monitoring notice shown to employees (GDPR Art. 13 and Art. 88).

Employee monitoring rests on the organisation's legitimate interest in protecting personal data (Art. 6(1)(f)
and Art. 32), not on the employee's consent, which is rarely freely given at work. The employee is therefore told
what is collected and why, and acknowledges that they have read it. The acknowledgement does not switch anything
on or off.

The same short text is set as the Windows sign-in notice on every enrolled laptop.
"""
from django.conf import settings

CAPTION = 'This device is monitored by Auditra'

WINDOWS_TEXT = (
    'This company laptop is monitored for the protection of personal data (GDPR Art. 32). '
    'Auditra records sign-ins, access to files in folders that hold personal data, USB storage, printing and '
    'visits to file-sharing and social-media sites. It does not record file contents, keystrokes, screens or '
    'other browsing. Ask your Data Protection Officer for details.'
)

COLLECTED = [
    'Windows sign-ins, unlocks, failed sign-ins and account lockouts on this laptop',
    'Opening, changing or deleting files inside the folders the organisation lists as holding personal data',
    'USB storage devices connected, and files copied to them',
    'Documents printed: the file name, printer and page count',
    'Visits to file-sharing and social-media sites only (the site name, not the page or anything typed)',
    'Changes to accounts, groups, the audit policy, scheduled tasks, and clearing of the Security log',
    'The size and age of files in the listed folders, to check retention periods',
]

NOT_COLLECTED = [
    'File contents',
    'Keystrokes, screenshots or camera',
    'Any other browsing history',
    'Personal folders outside the listed company folders',
]

PURPOSE = (
    'To detect and stop possible breaches of personal data held by the organisation, as required by GDPR '
    'Art. 5(1)(f), 25 and 32. Possible violations are reviewed by a compliance officer before any action.'
)

LAWFUL_BASIS = 'Legitimate interest, Art. 6(1)(f), in keeping personal data secure (Art. 32).'

RETENTION = 'Activity is kept for as long as it is needed to investigate it, and is deleted by the administrator.'


def version():
    return str(getattr(settings, 'MONITORING_NOTICE_VERSION', '1'))


def as_dict():
    return {
        'version': version(),
        'caption': CAPTION,
        'windows_text': WINDOWS_TEXT,
        'collected': COLLECTED,
        'not_collected': NOT_COLLECTED,
        'purpose': PURPOSE,
        'lawful_basis': LAWFUL_BASIS,
        'retention': RETENTION,
    }
