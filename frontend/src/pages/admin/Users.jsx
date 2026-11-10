import { ShieldCheck } from 'lucide-react'
import Crud from '../../components/Crud'
import { ago } from '../../lib/format'
import { PageHeader, Pill } from '../../components/ui'

const ROLE_LABELS = { admin: 'Administrator', compliance_officer: 'Compliance officer', employee: 'Employee (portal only)' }

export default function Users() {
  return (
    <>
      <PageHeader title="Console users" subtitle="People who can sign in to Auditra. Officers review incidents and records; administrators also configure the system. Employee portal logins are created from Employees & Access." />
      <Crud title="User" icon={ShieldCheck} path="/admin/users/"
        defaults={{ role: 'compliance_officer', is_active: true }}
        fields={[
          { name: 'username', label: 'Username', half: true },
          { name: 'email', label: 'Email', type: 'email', half: true },
          { name: 'first_name', label: 'First name', half: true },
          { name: 'last_name', label: 'Last name', half: true },
          { name: 'role', label: 'Role', type: 'select', options: { compliance_officer: 'Compliance officer', admin: 'Administrator' }, half: true },
          { name: 'password', label: 'Password', type: 'password', half: true, hint: 'At least 8 characters. Leave empty to keep the current one.' },
          { name: 'is_active', label: 'Can sign in', type: 'checkbox' },
        ]}
        columns={[
          { key: 'u', label: 'User', render: (r) => <div><p className="font-medium">{[r.first_name, r.last_name].filter(Boolean).join(' ') || r.username}</p><p className="text-xs text-ink-3">{r.username} · {r.email || 'no email'}</p></div> },
          { key: 'r', label: 'Role', render: (r) => <Pill tone={r.role === 'admin' ? 'accent' : 'default'}>{ROLE_LABELS[r.role] || r.role}</Pill> },
          { key: 'a', label: 'Status', render: (r) => <Pill tone={r.is_active ? 'ok' : 'crit'}>{r.is_active ? 'active' : 'disabled'}</Pill> },
          { key: 'l', label: 'Last sign-in', render: (r) => <span className="text-xs text-ink-3">{ago(r.last_login)}</span> },
        ]}
      />
    </>
  )
}
