import { useEffect, useState } from 'react'
import { HardDrive, Monitor, RotateCcw, ServerCog, ShieldOff, Trash2 } from 'lucide-react'
import api, { errorText } from '../../lib/api'
import { useLive } from '../../lib/live'
import { ago, full } from '../../lib/format'
import { DeviceStatePill, DownloadAgentButton } from '../../components/DeviceStatus'
import { Button, Card, CardHeader, Empty, ErrorNote, Input, Modal, PageHeader, Pill, Stat } from '../../components/ui'

const CHECK_LABELS = {
  security_log: 'Security log',
  audit_policy: 'Audit policy',
  file_auditing: 'File auditing',
  print_log: 'Print log',
  security_log_size: 'Security log size',
  sign_in_notice: 'Sign-in notice',
  clock: 'Clock',
}

/** What the agent checked and switched on in Windows itself; each failure says how to fix it. */
function WindowsChecks({ checks }) {
  const entries = Object.entries(checks || {})
  if (!entries.length) return <p className="text-[11px] text-ink-3">No Windows checks reported (agent older than 3.0).</p>
  const failing = entries.filter(([, c]) => !c.ok)
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([name, c]) => (
          <Pill key={name} tone={c.ok ? 'ok' : 'crit'}>
            <span title={c.detail}>{CHECK_LABELS[name] || name}</span>
          </Pill>
        ))}
      </div>
      {failing.map(([name, c]) => (
        <p key={name} className="mt-1 text-[11px] text-crit">
          {CHECK_LABELS[name] || name}: {c.detail}{c.fix && <span className="text-ink-3"> · {c.fix}</span>}
        </p>
      ))}
      {checks.file_auditing?.paths && (
        <p className="mt-1 font-mono text-[10px] text-ink-3">
          {Object.entries(checks.file_auditing.paths).map(([p, s]) => `${p}: ${s}`).join(' · ')}
        </p>
      )}
    </div>
  )
}

export default function Agents() {
  const { version } = useLive()
  const [health, setHealth] = useState(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const load = () => api.get('/admin/health/').then((r) => setHealth(r.data))
  useEffect(() => { load() }, [version])

  async function revoke(agent) {
    if (!window.confirm(agent.revoked ? `Allow ${agent.hostname} to send events again?` : `Revoke ${agent.hostname}? It will stop sending events.`)) return
    await api.post(`/admin/agents/${agent.id}/revoke/`)
    load()
  }

  async function reset() {
    setError('')
    try {
      const { data } = await api.post('/admin/reset-monitoring/', { confirm })
      setResult(data)
      setResetOpen(false)
      setConfirm('')
      load()
    } catch (e) { setError(errorText(e)) }
  }

  const c = health?.counts
  return (
    <>
      <PageHeader title="Agents & system health" subtitle="Machines that send activity, what each collector is doing, and the background compliance job."
        actions={<DownloadAgentButton url={health?.download_url} />} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Events stored" value={c?.events} icon={HardDrive} />
        <Stat label="Incidents" value={c?.incidents} />
        <Stat label="Employees" value={c?.employees} />
        <Stat label="Catalogue entries" value={c?.catalogue} />
        <Stat label="Rules enabled" value={c ? `${c.rules_enabled}/${c.rules_total}` : null} />
      </div>

      <Card className="mt-4">
        <CardHeader icon={Monitor} title="Agents" subtitle="Online means a heartbeat in the last 45 seconds" />
        {health?.agents?.length ? health.agents.map((a) => (
          <div key={a.id} className="flex flex-wrap items-start gap-4 border-b border-line/70 px-4 py-3 last:border-0">
            <div className="min-w-48">
              <p className="flex items-center gap-2 font-medium">
                {a.hostname}<DeviceStatePill device={a} />
              </p>
              <p className="mt-0.5 text-xs text-ink-3">{a.ip_address} · v{a.version} · last seen {ago(a.last_seen)}</p>
              <p className="mt-0.5 font-mono text-[11px] text-ink-3">user {a.console_user || '—'}</p>
              <p className="mt-0.5 text-[11px] text-ink-3">
                {a.owner ? <>owner <span className="font-medium text-ink-2">{a.owner.full_name}</span></> : 'no owner (registered with the shared key)'}
              </p>
            </div>
            <div className="flex min-w-64 flex-1 flex-col gap-2">
              <div className="flex flex-wrap gap-1.5">
                {a.is_admin ? <Pill tone="ok">Administrator</Pill> : <Pill tone="warn">not admin: Security log unread</Pill>}
                {Object.entries(a.collectors || {}).map(([name, status]) => (
                  <Pill key={name} tone={status === 'ok' ? 'ok' : 'crit'}>{name}{status !== 'ok' && `: ${status}`}</Pill>
                ))}
                {a.outbox > 0 && <Pill tone="warn">{a.outbox} event(s) waiting to send</Pill>}
                {a.revoked && <Pill tone="crit">revoked</Pill>}
              </div>
              <WindowsChecks checks={a.checks} />
            </div>
            <div className="text-right text-xs text-ink-3">
              <p className="tabular">{a.event_count} events</p>
              <p>registered {full(a.registered_at)}</p>
            </div>
            <Button size="sm" variant={a.revoked ? 'secondary' : 'danger'} icon={ShieldOff} onClick={() => revoke(a)}>{a.revoked ? 'Restore' : 'Revoke'}</Button>
          </div>
        )) : <Empty icon={Monitor} title="No agent has registered yet">Give the employee a portal login (Employees & Access), or an enrolment code, and run AuditraAgent.exe on their laptop.</Empty>}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader icon={ServerCog} title="Compliance job" subtitle="Deadlines, breaches and automated decisions, checked every minute" />
          {health?.jobs?.length ? health.jobs.map((j, i) => (
            <div key={i} className="flex items-center justify-between border-b border-line/70 px-4 py-2 text-sm last:border-0">
              <span className="tabular text-xs text-ink-2">{full(j.started_at)}</span>
              <span className="text-xs text-ink-3">{j.incidents_created} new incident(s)</span>
              <Pill tone={j.status === 'SUCCESS' ? 'ok' : j.status === 'RUNNING' ? 'accent' : 'crit'}>{j.status.toLowerCase()}</Pill>
            </div>
          )) : <Empty title="The job has not run yet" />}
        </Card>
        <Card>
          <CardHeader icon={RotateCcw} title="Reset recorded activity" subtitle="For rehearsals: deletes events, incidents and AI scores. Employees, catalogue and GDPR records stay." />
          <div className="px-4 py-4">
            <Button variant="danger" icon={Trash2} onClick={() => { setResetOpen(true); setError('') }}>Reset activity…</Button>
            {result && <p className="mt-3 text-xs text-ink-3">Deleted {result.events} events, {result.incidents} incidents, {result.ai_scores} AI scores.</p>}
          </div>
        </Card>
      </div>

      <Modal open={resetOpen} onClose={() => setResetOpen(false)} title="Delete all recorded activity?"
        subtitle="This permanently deletes every event, incident and AI score. It cannot be undone."
        footer={<><Button variant="ghost" onClick={() => setResetOpen(false)}>Cancel</Button><Button variant="danger" disabled={confirm !== 'RESET'} onClick={reset}>Delete activity</Button></>}>
        <p className="mb-2 text-sm text-ink-2">Type <span className="font-mono font-semibold text-ink">RESET</span> to confirm.</p>
        <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>
      </Modal>
    </>
  )
}
