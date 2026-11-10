import hashlib
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


SENSITIVITY_CHOICES = [
    ('LOW', 'Low'),
    ('MEDIUM', 'Medium'),
    ('HIGH', 'High'),
]
SENSITIVITY_RANK = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}

SEVERITY_CHOICES = [
    ('LOW', 'Low'),
    ('MEDIUM', 'Medium'),
    ('HIGH', 'High'),
    ('CRITICAL', 'Critical'),
]
SEVERITY_RANK = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}

CATEGORY_CHOICES = [
    ('GENERAL', 'General business'),
    ('FINANCIAL', 'Financial'),
    ('HR_EMPLOYEE', 'HR / employee records'),
    ('HEALTH', 'Health (special category)'),
    ('BIOMETRIC', 'Biometric (special category)'),
    ('CRIMINAL', 'Criminal offence data'),
    ('NATIONAL_ID', 'National ID (CNIC)'),
    ('CUSTOMER', 'Customer personal data'),
]
SPECIAL_CATEGORIES = {'HEALTH', 'BIOMETRIC'}

LAWFUL_BASIS_CHOICES = [
    ('CONSENT', 'Consent'),
    ('CONTRACT', 'Contract'),
    ('LEGAL_OBLIGATION', 'Legal obligation'),
    ('VITAL_INTEREST', 'Vital interest'),
    ('PUBLIC_TASK', 'Public task'),
    ('LEGITIMATE_INTEREST', 'Legitimate interest'),
]


class AuditraUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('compliance_officer', 'Compliance Officer'),
        ('employee', 'Employee'),
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='compliance_officer'
    )
    # Set for role 'employee': the monitored person this login belongs to (their own portal only).
    employee = models.OneToOneField(
        'Employee', null=True, blank=True, on_delete=models.CASCADE, related_name='login'
    )

    def is_admin(self):
        return self.role == 'admin'

    def is_compliance_officer(self):
        return self.role == 'compliance_officer'


# ============================================================
# ORGANISATION: employees, accounts, catalogue, data subjects
# ============================================================

class Employee(models.Model):
    ROLE_CHOICES = [
        ('INTERN', 'Intern'),
        ('STAFF', 'Staff'),
        ('ANALYST', 'Analyst'),
        ('MANAGER', 'Manager'),
        ('HR_OFFICER', 'HR officer'),
        ('MEDICAL_OFFICER', 'Medical officer'),
        ('IT_ADMIN', 'IT administrator'),
        ('CONTRACTOR', 'Contractor'),
    ]
    TYPE_CHOICES = [
        ('STAFF', 'Staff'),
        ('VENDOR', 'Vendor / processor'),
    ]
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('LEFT', 'Left the organisation'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=120)
    employee_code = models.CharField(max_length=30, unique=True)
    email = models.EmailField(blank=True)
    department = models.CharField(max_length=60)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='STAFF')
    employment_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='STAFF')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    shift_start = models.TimeField(default='09:00')
    shift_end = models.TimeField(default='18:00')
    # Python weekday numbers (Monday=0) the employee is expected to work.
    work_days = models.JSONField(default=list)
    max_sensitivity = models.CharField(max_length=10, choices=SENSITIVITY_CHOICES, default='MEDIUM')
    allowed_categories = models.JSONField(default=list)
    left_at = models.DateTimeField(null=True, blank=True)
    # The monitoring notice (Art. 13 / 88): which version the employee acknowledged, and when.
    notice_version = models.CharField(max_length=20, blank=True)
    notice_acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'employees'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} ({self.employee_code})'

    def save(self, *args, **kwargs):
        if not self.work_days:
            self.work_days = [0, 1, 2, 3, 4]
        super().save(*args, **kwargs)

    def is_on_shift(self, moment):
        local = timezone.localtime(moment)
        if local.weekday() not in (self.work_days or [0, 1, 2, 3, 4]):
            return False
        start, end, now = self.shift_start, self.shift_end, local.time()
        if isinstance(start, str):
            start = timezone.datetime.strptime(start, '%H:%M').time()
        if isinstance(end, str):
            end = timezone.datetime.strptime(end, '%H:%M').time()
        if start <= end:
            return start <= now < end
        return now >= start or now < end


class EmployeeAccount(models.Model):
    """A Windows account (MACHINE\\user or DOMAIN\\user) that belongs to an employee."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='accounts')
    account = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'employee_accounts'
        ordering = ['account']

    def save(self, *args, **kwargs):
        self.account = normalize_account(self.account)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.account


def normalize_account(value):
    return (value or '').strip().replace('/', '\\').lower()


def normalize_path(value):
    return (value or '').strip().replace('/', '\\').rstrip('\\').lower()


class ProcessingActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity_name = models.CharField(max_length=200)
    purpose = models.CharField(max_length=200)
    legal_basis = models.CharField(max_length=30, choices=LAWFUL_BASIS_CHOICES, blank=True)
    data_categories = models.TextField(blank=True)
    retention_period = models.CharField(max_length=100, blank=True)
    security_measures = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.activity_name

    class Meta:
        db_table = 'processing_activities'
        ordering = ['activity_name']


class DataSubject(models.Model):
    """A person whose personal data the organisation holds (customer, patient, candidate)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    reference = models.CharField(max_length=60, unique=True)
    email = models.EmailField(blank=True)
    # File or folder that holds this person's data, e.g. C:\AuditraCompany\Customers\ali_khan_profile.csv
    path_prefix = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'data_subjects'
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.path_prefix = normalize_path(self.path_prefix)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.reference})'


class CatalogueEntry(models.Model):
    """Maps a folder or file on monitored machines to what kind of personal data it holds."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    path_prefix = models.CharField(max_length=400, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='GENERAL')
    sensitivity = models.CharField(max_length=10, choices=SENSITIVITY_CHOICES, default='MEDIUM')
    processing_activity = models.ForeignKey(
        ProcessingActivity, null=True, blank=True, on_delete=models.SET_NULL, related_name='catalogue_entries'
    )
    owner_department = models.CharField(max_length=60, blank=True)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'catalogue_entries'
        ordering = ['path_prefix']

    def save(self, *args, **kwargs):
        self.path_prefix = normalize_path(self.path_prefix)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} [{self.category}/{self.sensitivity}]'


class Agent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hostname = models.CharField(max_length=100, unique=True)
    token = models.CharField(max_length=64, unique=True)
    ip_address = models.CharField(max_length=50, blank=True)
    version = models.CharField(max_length=20, blank=True)
    is_admin = models.BooleanField(default=False)
    console_user = models.CharField(max_length=150, blank=True)
    collectors = models.JSONField(default=dict, blank=True)
    # Windows configuration the agent checked and applied itself (audit policy, SACLs, logs, clock).
    checks = models.JSONField(default=dict, blank=True)
    outbox = models.PositiveIntegerField(default=0)
    # The person this laptop is assigned to (set by code enrolment). USB plug-ins are attributed to them.
    employee = models.ForeignKey(
        'Employee', null=True, blank=True, on_delete=models.SET_NULL, related_name='agents'
    )
    revoked = models.BooleanField(default=False)
    registered_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agents'
        ordering = ['hostname']

    @staticmethod
    def new_token():
        return secrets.token_hex(32)

    @property
    def online(self):
        return bool(self.last_seen) and timezone.now() - self.last_seen < timedelta(seconds=45)

    def __str__(self):
        return self.hostname


ENROLMENT_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O or 1/I, easy to type from a screen


def hash_enrolment_code(code):
    clean = ''.join(ch for ch in (code or '').upper() if ch.isalnum())
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()


class EnrolmentCode(models.Model):
    """A one-time code that lets one laptop join Auditra for one employee. Only its hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='enrolment_codes')
    created_by = models.ForeignKey(AuditraUser, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'enrolment_codes'
        ordering = ['-created_at']

    @classmethod
    def issue(cls, employee, user, minutes):
        """Returns (record, plain code). The plain code is shown once and never stored."""
        raw = ''.join(secrets.choice(ENROLMENT_ALPHABET) for _ in range(8))
        record = cls.objects.create(
            code_hash=hash_enrolment_code(raw), employee=employee,
            created_by=user if user and user.is_authenticated else None,
            expires_at=timezone.now() + timedelta(minutes=minutes),
        )
        return record, f'{raw[:4]}-{raw[4:]}'

    @property
    def usable(self):
        return self.used_at is None and timezone.now() < self.expires_at


# ============================================================
# ACTIVITY AND DETECTION
# ============================================================

class Event(models.Model):
    TYPE_CHOICES = [
        ('LOGON', 'Logged on'),
        ('UNLOCK', 'Unlocked workstation'),
        ('LOCK', 'Locked workstation'),
        ('LOGON_FAILED', 'Failed logon'),
        ('ACCOUNT_CREATED', 'User account created'),
        ('GROUP_MEMBER_ADDED', 'Added to security group'),
        ('ACCOUNT_LOCKED', 'Account locked out'),
        ('LOG_CLEARED', 'Security log cleared'),
        ('AUDIT_POLICY_CHANGED', 'Audit policy changed'),
        ('TASK_CREATED', 'Scheduled task created'),
        ('FILE_READ', 'Opened file'),
        ('FILE_WRITE', 'Modified file'),
        ('FILE_DELETE', 'Deleted file'),
        ('USB_CONNECTED', 'USB storage connected'),
        ('FILE_COPY_TO_USB', 'Copied file to USB'),
        ('PRINT', 'Printed document'),
        ('WEB_VISIT', 'Visited website'),
        ('RETENTION_EXCEEDED', 'File kept past retention'),
        ('AUTOMATED_DECISION', 'Automated decision'),
    ]
    LOGON_EVENT_TYPES = {'LOGON', 'UNLOCK'}
    FILE_EVENT_TYPES = {'FILE_READ', 'FILE_WRITE', 'FILE_DELETE', 'FILE_COPY_TO_USB', 'PRINT'}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    event_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    machine = models.CharField(max_length=100)
    account = models.CharField(max_length=150, db_index=True)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    path = models.CharField(max_length=500, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    process = models.CharField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=255, blank=True)
    source_ip = models.CharField(max_length=60, blank=True)
    logon_type = models.PositiveSmallIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    catalogue_entry = models.ForeignKey(
        CatalogueEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name='events'
    )
    category = models.CharField(max_length=20, blank=True)
    sensitivity = models.CharField(max_length=10, blank=True)
    data_subject = models.ForeignKey(
        DataSubject, null=True, blank=True, on_delete=models.SET_NULL, related_name='events'
    )
    outside_shift = models.BooleanField(default=False)
    source = models.CharField(max_length=120, blank=True)
    source_event_id = models.PositiveIntegerField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = 'events'
        ordering = ['-occurred_at']

    def __str__(self):
        return f'{self.account} {self.event_type} {self.path or self.domain or self.device}'

    @property
    def description(self):
        label = dict(self.TYPE_CHOICES).get(self.event_type, self.event_type)
        target = self.path or self.domain or self.device or self.details.get('target', '')
        return f'{label} {target}'.strip()


class Rule(models.Model):
    KIND_CHOICES = [
        ('VIOLATION', 'Potential violation'),
        ('INDICATOR', 'Risk indicator'),
        ('ANOMALY', 'AI anomaly'),
    ]
    SOURCE_CHOICES = [
        ('EVENT', 'Endpoint event'),
        ('WINDOW', 'Pattern over time'),
        ('WORKFLOW', 'GDPR records'),
        ('AI', 'AI model'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=150)
    gdpr_article = models.CharField(max_length=120)
    articles = models.JSONField(default=list)
    description = models.TextField()
    logic_definition = models.TextField(blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='VIOLATION')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='EVENT')
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.code} ({self.gdpr_article})'

    class Meta:
        db_table = 'rules'
        ordering = ['code']


class Incident(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('ACKNOWLEDGED', 'Acknowledged'),
        ('INVESTIGATING', 'Investigating'),
        ('ESCALATED', 'Escalated to DPO'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False positive'),
    ]
    CLOSED_STATUSES = {'RESOLVED', 'FALSE_POSITIVE'}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.PositiveIntegerField(unique=True, editable=False)
    kind = models.CharField(max_length=10, choices=Rule.KIND_CHOICES, default='VIOLATION')
    rule = models.ForeignKey(Rule, null=True, blank=True, on_delete=models.SET_NULL, related_name='incidents')
    rule_codes = models.JSONField(default=list)
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name='incidents'
    )
    account = models.CharField(max_length=150, blank=True)
    machine = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    reasons = models.JSONField(default=list)
    articles = models.JSONField(default=list)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    rule_severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    score = models.PositiveSmallIntegerField(default=0)
    score_breakdown = models.JSONField(default=list)
    ai_score = models.FloatField(null=True, blank=True)
    ai_reason = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='OPEN')
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    events = models.ManyToManyField(Event, blank=True, related_name='incidents')
    dedupe_key = models.CharField(max_length=200, unique=True)
    assigned_to = models.ForeignKey(
        AuditraUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_incidents'
    )

    class Meta:
        db_table = 'incidents'
        ordering = ['-detected_at']

    def save(self, *args, **kwargs):
        if not self.number:
            last = Incident.objects.order_by('-number').values_list('number', flat=True).first()
            self.number = (last or 1000) + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f'INC-{self.number} {self.title}'


class IncidentAction(models.Model):
    ACTION_CHOICES = [
        ('ACKNOWLEDGE', 'Acknowledged'),
        ('INVESTIGATE', 'Started investigation'),
        ('ESCALATE', 'Escalated to DPO'),
        ('RESOLVE', 'Resolved'),
        ('FALSE_POSITIVE', 'Marked false positive'),
        ('REOPEN', 'Reopened'),
        ('NOTE', 'Added note'),
        ('REPORT_LOST_DEVICE', 'Reported lost device (breach opened)'),
        ('SCORE_UPDATED', 'Score updated'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='actions')
    actor = models.ForeignKey(AuditraUser, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'incident_actions'
        ordering = ['created_at']


class AiDayScore(models.Model):
    """Latest AI anomaly score for one employee (or unlinked account) on one local day."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_key = models.CharField(max_length=150)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.CASCADE, related_name='ai_days')
    day = models.DateField()
    score = models.FloatField()
    deviation = models.FloatField()
    features = models.JSONField(default=dict)
    contributions = models.JSONField(default=list)
    baseline = models.CharField(max_length=20)
    reason = models.CharField(max_length=400, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_day_scores'
        unique_together = [('subject_key', 'day')]
        ordering = ['-day']


# ============================================================
# GDPR RECORDS (workflow evidence, "R" in the mapping workbook)
# ============================================================

class ConsentRecord(models.Model):
    STATUS_CHOICES = [
        ('GIVEN', 'Given'),
        ('WITHDRAWN', 'Withdrawn'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_subject = models.ForeignKey(DataSubject, on_delete=models.CASCADE, related_name='consents')
    purpose = models.CharField(max_length=200)
    lawful_basis = models.CharField(max_length=30, choices=LAWFUL_BASIS_CHOICES, default='CONSENT')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='GIVEN')
    given_at = models.DateTimeField(default=timezone.now)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'consent_records'
        ordering = ['-given_at']

    def __str__(self):
        return f'{self.data_subject} - {self.purpose} - {self.status}'


class DataSubjectRequest(models.Model):
    RIGHT_TYPE_CHOICES = [
        ('ACCESS', 'Access (Art. 15)'),
        ('RECTIFICATION', 'Rectification (Art. 16)'),
        ('ERASURE', 'Erasure (Art. 17)'),
        ('RESTRICTION', 'Restriction (Art. 18)'),
        ('PORTABILITY', 'Portability (Art. 20)'),
        ('OBJECTION', 'Objection (Art. 21)'),
    ]
    RIGHT_ARTICLE = {
        'ACCESS': '15', 'RECTIFICATION': '16', 'ERASURE': '17',
        'RESTRICTION': '18', 'PORTABILITY': '20', 'OBJECTION': '21',
    }
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In progress'),
        ('COMPLETED', 'Completed'),
        ('DENIED', 'Denied'),
    ]
    OPEN_STATUSES = {'PENDING', 'IN_PROGRESS'}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_subject = models.ForeignKey(DataSubject, on_delete=models.CASCADE, related_name='requests')
    right_type = models.CharField(max_length=20, choices=RIGHT_TYPE_CHOICES)
    received_at = models.DateTimeField(default=timezone.now)
    response_deadline = models.DateTimeField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    completed_at = models.DateTimeField(null=True, blank=True)
    exemption_note = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'data_subject_requests'
        ordering = ['response_deadline']

    def save(self, *args, **kwargs):
        if not self.response_deadline:
            self.response_deadline = (self.received_at or timezone.now()) + timedelta(days=30)
        if self.status in ('COMPLETED', 'DENIED') and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.data_subject} - {self.right_type} - {self.status}'


class BreachRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, null=True, blank=True, on_delete=models.SET_NULL, related_name='breaches')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    detected_at = models.DateTimeField(default=timezone.now)
    notification_deadline = models.DateTimeField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='HIGH')
    high_risk = models.BooleanField(default=True)
    authority_notified_at = models.DateTimeField(null=True, blank=True)
    subjects_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'breach_records'
        ordering = ['-detected_at']

    def save(self, *args, **kwargs):
        if not self.notification_deadline:
            self.notification_deadline = (self.detected_at or timezone.now()) + timedelta(hours=72)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Breach - {self.title}'


class AutomatedDecision(models.Model):
    """A decision made by a business system without a person, sent through the decisions API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    system = models.CharField(max_length=100)
    subject_reference = models.CharField(max_length=100)
    data_subject = models.ForeignKey(
        DataSubject, null=True, blank=True, on_delete=models.SET_NULL, related_name='decisions'
    )
    decision = models.CharField(max_length=200)
    significant_effect = models.BooleanField(default=True)
    made_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.CharField(max_length=100, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'automated_decisions'
        ordering = ['-made_at']


class DPORecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_name = models.CharField(max_length=200, default='Auditra Organization')
    dpo_required = models.BooleanField(default=True)
    name = models.CharField(max_length=100, blank=True)
    contact = models.EmailField(blank=True)
    designated_at = models.DateField(null=True, blank=True)
    scope = models.TextField(blank=True)
    independent = models.BooleanField(default=False)
    direct_access_to_management = models.BooleanField(default=False)
    conflict_free = models.BooleanField(default=False)
    published_contact_details = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def compliance_status(self):
        if not self.dpo_required:
            return 'NOT_REQUIRED'

        required_details = [
            self.name.strip(),
            self.contact.strip(),
            self.designated_at,
            self.scope.strip(),
            self.independent,
            self.direct_access_to_management,
            self.conflict_free,
            self.published_contact_details,
        ]
        if all(required_details):
            return 'COMPLIANT'
        if not self.name.strip() or not self.designated_at:
            return 'MISSING'
        return 'REVIEW_REQUIRED'

    def __str__(self):
        return f"DPO - {self.name or 'Not designated'} - {self.compliance_status}"

    class Meta:
        db_table = 'dpo_records'


# ============================================================
# OPERATIONS
# ============================================================

class AuditEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(AuditraUser, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=200)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_entries'
        ordering = ['-created_at']


class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(AuditraUser, null=True, blank=True, on_delete=models.SET_NULL)
    period_covered = models.CharField(max_length=100)
    violation_summary = models.TextField()
    export_reference = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return f"Report - {self.period_covered} - {self.generated_at}"

    class Meta:
        db_table = 'reports'


class NotificationLog(models.Model):
    EVENT_CHOICES = [
        ('CRITICAL_VIOLATION', 'Critical violation'),
        ('BREACH_DEADLINE', 'Breach deadline'),
        ('DSR_DEADLINE', 'Data-subject request deadline'),
        ('DPO_STATUS', 'DPO status'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    event_key = models.CharField(max_length=255, unique=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.event_type} - {self.recipient} - {self.status}"

    class Meta:
        db_table = 'notification_logs'
        ordering = ['-created_at']


class ComplianceJobRun(models.Model):
    TRIGGER_CHOICES = [
        ('MANUAL', 'Manual'),
        ('SCHEDULED', 'Scheduled'),
    ]
    STATUS_CHOICES = [
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('SKIPPED', 'Skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trigger = models.CharField(max_length=10, choices=TRIGGER_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='RUNNING')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    incidents_created = models.PositiveIntegerField(default=0)
    notifications_sent = models.PositiveIntegerField(default=0)
    notifications_skipped = models.PositiveIntegerField(default=0)
    notifications_failed = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    def __str__(self):
        return f'{self.trigger} compliance run - {self.status} - {self.started_at}'

    class Meta:
        db_table = 'compliance_job_runs'
        ordering = ['-started_at']
