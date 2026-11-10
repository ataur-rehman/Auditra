from django.utils import timezone
from rest_framework import serializers

from .models import (
    CATEGORY_CHOICES, Agent, AuditEntry, AuditraUser, AutomatedDecision, BreachRecord, CatalogueEntry,
    ConsentRecord, DataSubject, DataSubjectRequest, DPORecord, Employee, EmployeeAccount, Event, Incident,
    IncidentAction, ProcessingActivity, Rule,
)

CATEGORY_CODES = {code for code, _ in CATEGORY_CHOICES}


class EmployeeBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'full_name', 'employee_code', 'department', 'role', 'employment_type', 'status']


class EventSerializer(serializers.ModelSerializer):
    employee = EmployeeBriefSerializer(read_only=True)
    type_label = serializers.CharField(source='get_event_type_display', read_only=True)
    catalogue_name = serializers.CharField(source='catalogue_entry.name', read_only=True, default='')
    data_subject_name = serializers.CharField(source='data_subject.name', read_only=True, default='')

    class Meta:
        model = Event
        fields = [
            'id', 'event_type', 'type_label', 'occurred_at', 'received_at', 'machine', 'account', 'employee',
            'path', 'file_name', 'process', 'domain', 'device', 'source_ip', 'logon_type', 'details',
            'catalogue_name', 'category', 'sensitivity', 'data_subject_name', 'outside_shift', 'source',
            'source_event_id',
        ]


class IncidentActionSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source='actor.username', read_only=True, default='system')
    action_label = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = IncidentAction
        fields = ['id', 'action', 'action_label', 'note', 'actor', 'created_at']


class IncidentListSerializer(serializers.ModelSerializer):
    employee = EmployeeBriefSerializer(read_only=True)
    rule_code = serializers.CharField(source='rule.code', read_only=True, default='')
    event_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Incident
        fields = [
            'id', 'number', 'kind', 'rule_code', 'rule_codes', 'title', 'summary', 'articles', 'severity',
            'rule_severity', 'score', 'ai_score', 'status', 'employee', 'account', 'machine', 'detected_at',
            'updated_at', 'event_count',
        ]


class IncidentDetailSerializer(IncidentListSerializer):
    events = EventSerializer(many=True, read_only=True)
    actions = IncidentActionSerializer(many=True, read_only=True)
    rule_description = serializers.CharField(source='rule.description', read_only=True, default='')
    breaches = serializers.SerializerMethodField()

    class Meta(IncidentListSerializer.Meta):
        fields = IncidentListSerializer.Meta.fields + [
            'reasons', 'score_breakdown', 'ai_reason', 'events', 'actions', 'rule_description', 'breaches',
        ]

    def get_breaches(self, obj):
        return [{'id': str(b.id), 'title': b.title, 'deadline': b.notification_deadline} for b in obj.breaches.all()]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        first = obj.events.select_related('catalogue_entry', 'data_subject').order_by('occurred_at').first()
        data['data'] = None
        if first and first.catalogue_entry:
            data['data'] = {'name': first.catalogue_entry.name, 'category': first.catalogue_entry.category,
                            'sensitivity': first.catalogue_entry.sensitivity,
                            'subject': first.data_subject.name if first.data_subject else '',
                            'subject_id': str(first.data_subject_id) if first.data_subject_id else ''}
        data['occurred_at'] = first.occurred_at if first else obj.detected_at
        return data


class EmployeeAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeAccount
        fields = ['id', 'account', 'created_at']


class EmployeeSerializer(serializers.ModelSerializer):
    accounts = EmployeeAccountSerializer(many=True, read_only=True)
    role_label = serializers.CharField(source='get_role_display', read_only=True)
    login_username = serializers.SerializerMethodField()
    devices = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'full_name', 'employee_code', 'email', 'department', 'role', 'role_label', 'employment_type',
            'status', 'shift_start', 'shift_end', 'work_days', 'max_sensitivity', 'allowed_categories',
            'left_at', 'accounts', 'created_at', 'login_username', 'devices', 'notice_version',
            'notice_acknowledged_at',
        ]
        read_only_fields = ['notice_version', 'notice_acknowledged_at']

    def get_login_username(self, obj):
        try:
            return obj.login.username
        except AuditraUser.DoesNotExist:
            return None

    def get_devices(self, obj):
        return [{'id': str(a.id), 'hostname': a.hostname, 'online': a.online, 'last_seen': a.last_seen}
                for a in obj.agents.all() if not a.revoked]

    def validate_allowed_categories(self, value):
        unknown = set(value or []) - CATEGORY_CODES
        if unknown:
            raise serializers.ValidationError(f'Unknown categories: {", ".join(sorted(unknown))}')
        return sorted(set(value or []))

    def validate_work_days(self, value):
        if any(not isinstance(d, int) or d < 0 or d > 6 for d in value or []):
            raise serializers.ValidationError('Work days are numbers 0 (Monday) to 6 (Sunday).')
        return sorted(set(value or []))

    def validate(self, attrs):
        status = attrs.get('status', getattr(self.instance, 'status', 'ACTIVE'))
        if status == 'LEFT' and not attrs.get('left_at') and not getattr(self.instance, 'left_at', None):
            attrs['left_at'] = timezone.now()
        if status == 'ACTIVE':
            attrs['left_at'] = None
        return attrs


class ProcessingActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingActivity
        fields = ['id', 'activity_name', 'purpose', 'legal_basis', 'data_categories', 'retention_period',
                  'security_measures', 'created_at']


class CatalogueEntrySerializer(serializers.ModelSerializer):
    processing_activity_name = serializers.CharField(source='processing_activity.activity_name', read_only=True,
                                                     default='')

    class Meta:
        model = CatalogueEntry
        fields = ['id', 'name', 'path_prefix', 'category', 'sensitivity', 'processing_activity',
                  'processing_activity_name', 'owner_department', 'retention_days', 'created_at']


class DataSubjectSerializer(serializers.ModelSerializer):
    consent_status = serializers.SerializerMethodField()
    open_requests = serializers.SerializerMethodField()

    class Meta:
        model = DataSubject
        fields = ['id', 'name', 'reference', 'email', 'path_prefix', 'consent_status', 'open_requests', 'created_at']

    def get_consent_status(self, obj):
        statuses = {c.status for c in obj.consents.all()}
        if not statuses:
            return 'NONE'
        return 'GIVEN' if 'GIVEN' in statuses else 'WITHDRAWN'

    def get_open_requests(self, obj):
        return sum(1 for r in obj.requests.all() if r.status in DataSubjectRequest.OPEN_STATUSES)


class ConsentRecordSerializer(serializers.ModelSerializer):
    data_subject_name = serializers.CharField(source='data_subject.name', read_only=True)

    class Meta:
        model = ConsentRecord
        fields = ['id', 'data_subject', 'data_subject_name', 'purpose', 'lawful_basis', 'status', 'given_at',
                  'withdrawn_at']

    def validate(self, attrs):
        status = attrs.get('status', getattr(self.instance, 'status', 'GIVEN'))
        if status == 'WITHDRAWN' and not attrs.get('withdrawn_at') and not getattr(self.instance, 'withdrawn_at', None):
            attrs['withdrawn_at'] = timezone.now()
        if status == 'GIVEN':
            attrs['withdrawn_at'] = None
        return attrs


class DataSubjectRequestSerializer(serializers.ModelSerializer):
    data_subject_name = serializers.CharField(source='data_subject.name', read_only=True)
    article = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = DataSubjectRequest
        fields = ['id', 'data_subject', 'data_subject_name', 'right_type', 'article', 'received_at',
                  'response_deadline', 'status', 'completed_at', 'exemption_note', 'notes', 'overdue']
        extra_kwargs = {'response_deadline': {'required': False}}

    def get_article(self, obj):
        return DataSubjectRequest.RIGHT_ARTICLE.get(obj.right_type)

    def get_overdue(self, obj):
        return obj.status in DataSubjectRequest.OPEN_STATUSES and obj.response_deadline < timezone.now()

    def update(self, instance, validated_data):
        if validated_data.get('status') in DataSubjectRequest.OPEN_STATUSES:
            validated_data['completed_at'] = None
        return super().update(instance, validated_data)


class BreachRecordSerializer(serializers.ModelSerializer):
    incident_number = serializers.IntegerField(source='incident.number', read_only=True, default=None)
    hours_left = serializers.SerializerMethodField()

    class Meta:
        model = BreachRecord
        fields = ['id', 'incident', 'incident_number', 'title', 'description', 'detected_at',
                  'notification_deadline', 'severity', 'high_risk', 'authority_notified_at', 'subjects_notified_at',
                  'hours_left']
        extra_kwargs = {'notification_deadline': {'required': False}}

    def get_hours_left(self, obj):
        return round((obj.notification_deadline - timezone.now()).total_seconds() / 3600, 1)


class AutomatedDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomatedDecision
        fields = ['id', 'system', 'subject_reference', 'data_subject', 'decision', 'significant_effect', 'made_at',
                  'reviewed_by', 'reviewed_at']


class DPORecordSerializer(serializers.ModelSerializer):
    compliance_status = serializers.CharField(read_only=True)

    class Meta:
        model = DPORecord
        fields = ['id', 'organization_name', 'dpo_required', 'name', 'contact', 'designated_at', 'scope',
                  'independent', 'direct_access_to_management', 'conflict_free', 'published_contact_details',
                  'compliance_status', 'updated_at']


class RuleSerializer(serializers.ModelSerializer):
    incident_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Rule
        fields = ['id', 'code', 'title', 'gdpr_article', 'articles', 'description', 'severity', 'kind', 'source',
                  'enabled', 'incident_count']
        read_only_fields = ['code', 'title', 'gdpr_article', 'articles', 'description', 'severity', 'kind', 'source']


class AgentSerializer(serializers.ModelSerializer):
    online = serializers.BooleanField(read_only=True)
    event_count = serializers.IntegerField(read_only=True, default=0)
    owner = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = ['id', 'hostname', 'ip_address', 'version', 'is_admin', 'console_user', 'collectors', 'checks',
                  'outbox', 'owner', 'revoked', 'registered_at', 'last_seen', 'online', 'event_count']

    def get_owner(self, obj):
        if not obj.employee_id:
            return None
        return {'id': str(obj.employee_id), 'full_name': obj.employee.full_name}


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = AuditraUser
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'role', 'is_active', 'last_login',
                  'date_joined', 'password']
        read_only_fields = ['last_login', 'date_joined']

    def validate_password(self, value):
        if value and len(value) < 8:
            raise serializers.ValidationError('Use at least 8 characters.')
        return value

    def validate_role(self, value):
        # An employee login must belong to an employee record; those are created from Employees & Access.
        linked = bool(self.instance and self.instance.employee_id)
        if value == 'employee' and not linked:
            raise serializers.ValidationError('Create employee logins from Employees & Access.')
        if value != 'employee' and linked:
            raise serializers.ValidationError('This is an employee portal login; it cannot become an officer or '
                                              'administrator account.')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'A password is required for a new user.'})
        user = AuditraUser(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class AuditEntrySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source='actor.username', read_only=True, default='system')

    class Meta:
        model = AuditEntry
        fields = ['id', 'actor', 'action', 'target', 'details', 'created_at']
