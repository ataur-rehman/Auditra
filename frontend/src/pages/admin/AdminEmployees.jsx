import { useEffect, useState } from 'react'
import { KeyRound, Link2, UserCog, UserRound, X } from 'lucide-react'
import api, { errorText } from '../../lib/api'
import { useLive } from '../../lib/live'
import { CATEGORIES, DAYS, EMPLOYEE_ROLES, ago, full } from '../../lib/format'
import Crud from '../../components/Crud'
import LinkAccountModal from '../../components/LinkAccount'
import { Button, Card, CardHeader, Empty, Modal, PageHeader, Pill } from '../../components/ui'

const DAY_OPTIONS = Object.fromEntries(DAYS.map((d, i) => [i, d]))

function AccountsCell({ row, reload }) {
  async function unlink(account) {
    if (!window.confirm(`Unlink ${account.account} from ${row.full_name}?`)) return
    await api.delete(`/admin/employees/${row.id}/accounts/${account.id}/`)
    reload()
  }
  return (
    <div className="flex flex-col gap-1">
      {row.accounts.map((a) => (
        <span key={a.id} className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-2">
          {a.account}
          <button onClick={(e) => { e.stopPropagation(); unlink(a) }} className="text-ink-3 hover:text-crit"><X size={11} /></button>
        </span>
      ))}
      {!row.accounts.length && <span className="text-xs text-ink-3">none</span>}
    </div>
  )
}

function PortalCell({ row }) {
  return (
    <div className="flex flex-col gap-1 text-xs">
      {row.login_username
        ? <span className="font-mono text-[11px] text-ink-2">login {row.login_username}</span>
        : <span className="text-ink-3">no portal login</span>}
      {row.notice_acknowledged_at
        ? <Pill tone="ok">notice read · v{row.notice_version}</Pill>
        : <Pill tone="warn">notice not acknowledged</Pill>}
      {row.devices.map((d) => (
        <span key={d.id} className="inline-flex items-center gap-1 text-ink-2">
          <span className={`h-1.5 w-1.5 rounded-full ${d.online ? 'bg-ok' : 'bg-ink-3'}`} />{d.hostname}
        </span>
      ))}
    </div>
  )
}

/** Shows a password or an enrolment code once. Neither is stored in readable form on the server. */
function SecretModal({ secret, onClose }) {
  return (
    <Modal open={Boolean(secret)} onClose={onClose} title={secret?.title} subtitle={secret?.subtitle}
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      {secret?.rows.map(([label, value]) => (
        <div key={label} className="mb-3">
          <p className="text-xs text-ink-3">{label}</p>
          <p className="select-all font-mono text-lg font-semibold tracking-wider text-ink">{value}</p>
        </div>
      ))}
      <p className="text-xs text-ink-3">This is shown once. Give it to the employee directly, not by a shared channel.</p>
    </Modal>
  )
}

function Unlinked({ version, onLink }) {
  const [rows, setRows] = useState([])
  useEffect(() => { api.get('/admin/unlinked-accounts/').then((r) => setRows(r.data)) }, [version])

  return (
    <Card>
      <CardHeader title="Accounts seen by agents but not linked" subtitle="Link each Windows account to the employee who uses it. Its activity is then checked against that person's permissions." />
      {rows.length ? (
        <div className="divide-y divide-line">
          {rows.map((r) => (
            <div key={`${r.account}-${r.machine}`} className="flex items-center gap-4 px-5 py-3 text-sm">
              <span className="flex-1 font-mono text-xs">{r.account}</span>
              <span className="text-xs text-ink-3">{r.machine}</span>
              <span className="tabular text-xs text-ink-3">{r.events} events · {ago(r.last_seen)}</span>
              <Button size="sm" icon={Link2} onClick={() => onLink({ account: r.account })}>Link</Button>
            </div>
          ))}
        </div>
      ) : <Empty title="Every account seen so far is linked" />}
    </Card>
  )
}

export default function AdminEmployees() {
  const { version } = useLive()
  const [tick, setTick] = useState(0)
  const [linking, setLinking] = useState(null)
  const [secret, setSecret] = useState(null)

  async function createLogin(row) {
    const reset = Boolean(row.login_username)
    if (reset && !window.confirm(`Reset the portal password of ${row.full_name}?`)) return
    try {
      const { data } = await api.post(`/admin/employees/${row.id}/login/`, {})
      setSecret({ title: reset ? 'New portal password' : 'Portal login created', subtitle: `${row.full_name} signs in at this console's address.`,
        rows: [['Username', data.username], ['Temporary password', data.password]] })
      setTick((t) => t + 1)
    } catch (e) { window.alert(errorText(e)) }
  }

  async function issueCode(row) {
    try {
      const { data } = await api.post(`/admin/employees/${row.id}/enrolment-code/`)
      setSecret({ title: 'Enrolment code', subtitle: `Type it in the Auditra Agent setup window on ${row.full_name}'s laptop. Valid until ${full(data.expires_at)}.`,
        rows: [['Code', data.code]] })
    } catch (e) { window.alert(errorText(e)) }
  }

  return (
    <>
      <PageHeader title="Employees & access" subtitle="Who may see what, and when. These permissions are what the role-scope, category, shift and vendor rules check." />
      <div className="space-y-4">
        <Crud title="Employee" icon={UserCog} path="/admin/employees/" deps={[tick]} onSaved={() => setTick((t) => t + 1)}
          defaults={{ role: 'STAFF', employment_type: 'STAFF', status: 'ACTIVE', shift_start: '09:00', shift_end: '18:00', work_days: [0, 1, 2, 3, 4], max_sensitivity: 'MEDIUM', allowed_categories: [] }}
          fields={[
            { name: 'full_name', label: 'Full name', half: true },
            { name: 'employee_code', label: 'Employee code', half: true, placeholder: 'E-1001' },
            { name: 'department', label: 'Department', half: true, placeholder: 'Finance' },
            { name: 'email', label: 'Email', type: 'email', half: true },
            { name: 'role', label: 'Role', type: 'select', options: EMPLOYEE_ROLES, half: true },
            { name: 'employment_type', label: 'Type', type: 'select', options: { STAFF: 'Staff', VENDOR: 'Vendor / processor (Art. 29)' }, half: true },
            { name: 'shift_start', label: 'Shift starts', type: 'time', half: true },
            { name: 'shift_end', label: 'Shift ends', type: 'time', half: true },
            { name: 'work_days', label: 'Working days', type: 'multiselect', options: DAY_OPTIONS },
            { name: 'max_sensitivity', label: 'Highest sensitivity allowed', type: 'select', options: ['LOW', 'MEDIUM', 'HIGH'], half: true },
            { name: 'status', label: 'Status', type: 'select', options: { ACTIVE: 'Active', LEFT: 'Left the organisation' }, half: true },
            { name: 'allowed_categories', label: 'Data categories allowed', type: 'multiselect', options: CATEGORIES, hint: 'General business data is always allowed' },
          ]}
          columns={[
            { key: 'n', label: 'Employee', render: (r) => <div><p className="font-medium">{r.full_name}</p><p className="text-xs text-ink-3">{r.employee_code} · {r.department} · {r.role_label}</p></div> },
            { key: 't', label: 'Status', render: (r) => <div className="flex flex-wrap gap-1">{r.employment_type === 'VENDOR' && <Pill tone="warn">Vendor</Pill>}<Pill tone={r.status === 'ACTIVE' ? 'ok' : 'crit'}>{r.status.toLowerCase()}</Pill></div> },
            { key: 's', label: 'Shift', render: (r) => <span className="tabular text-xs text-ink-2">{r.shift_start.slice(0, 5)}–{r.shift_end.slice(0, 5)}<br />{r.work_days.map((d) => DAYS[d]).join(' ')}</span> },
            { key: 'p', label: 'Permissions', render: (r) => <div className="text-xs text-ink-2">up to {r.max_sensitivity}<div className="mt-1 flex flex-wrap gap-1">{r.allowed_categories.map((c) => <Pill key={c}>{c}</Pill>)}</div></div> },
            { key: 'a', label: 'Windows accounts', render: (r) => <AccountsCell row={r} reload={() => setTick((t) => t + 1)} /> },
            { key: 'o', label: 'Portal & laptops', render: (r) => <PortalCell row={r} /> },
          ]}
          extraActions={(row) => (
            <>
              <Button size="sm" variant="ghost" icon={Link2} title="Link account" onClick={() => setLinking({ employee: row })} />
              <Button size="sm" variant="ghost" icon={UserRound} title={row.login_username ? 'Reset portal password' : 'Create portal login'} onClick={() => createLogin(row)} />
              <Button size="sm" variant="ghost" icon={KeyRound} title="Enrolment code for a laptop" onClick={() => issueCode(row)} />
            </>
          )}
          emptyText="No employees yet. Add the people whose laptops are monitored."
        />
        <Unlinked version={`${version}-${tick}`} onLink={setLinking} />
      </div>
      <LinkAccountModal open={Boolean(linking)} account={linking?.account} employee={linking?.employee}
        onClose={() => setLinking(null)} onLinked={() => setTick((t) => t + 1)} />
      <SecretModal secret={secret} onClose={() => setSecret(null)} />
    </>
  )
}
