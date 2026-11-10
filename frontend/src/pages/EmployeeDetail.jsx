import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowLeft, BrainCircuit, Download, ShieldAlert } from 'lucide-react'
import api, { download } from '../lib/api'
import { useLive } from '../lib/live'
import { DAYS } from '../lib/format'
import { useThemeColors } from '../lib/theme'
import { EventRow, IncidentRow } from '../components/Feeds'
import { DeviceRow } from '../components/DeviceStatus'
import { Button, Card, CardHeader, Empty, PageHeader, Pill, Spinner, Stat } from '../components/ui'

export default function EmployeeDetail() {
  const { id } = useParams()
  const { version } = useLive()
  const [emp, setEmp] = useState(null)
  const colors = useThemeColors()

  useEffect(() => { api.get(`/employees/${id}/`).then((r) => setEmp(r.data)) }, [id, version])
  if (!emp) return <Spinner />

  const today = emp.ai_days[emp.ai_days.length - 1]
  const series = emp.ai_days.map((d) => ({ day: d.day.slice(5), score: Math.round(d.score) }))

  return (
    <>
      <Link to="/employees" className="mb-3 inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-ink"><ArrowLeft size={13} /> Employees</Link>
      <PageHeader
        title={emp.full_name}
        subtitle={`${emp.employee_code} · ${emp.role_label} · ${emp.department}`}
        actions={<Button icon={Download} size="sm" onClick={() => download(`/reports/compliance.pdf?days=30&employee=${emp.id}`, `auditra_${emp.employee_code}.pdf`)}>Employee report</Button>}
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Open incidents" value={emp.risk?.open_incidents} tone={emp.risk?.open_incidents ? 'high' : undefined} />
        <Stat label="Violations, last 7 days" value={emp.risk?.week_violations} hint={emp.risk?.repeat_offender ? 'Art. 83 escalation active' : 'below Art. 83 threshold (3)'} tone={emp.risk?.repeat_offender ? 'crit' : undefined} />
        <Stat label="Highest open score" value={emp.risk?.risk_score} />
        <Stat label="AI score today" value={today ? Math.round(today.score) : '—'} tone={today?.score >= 60 ? 'high' : undefined} hint={today?.baseline === 'personal' ? 'vs own baseline' : 'vs CERT population baseline'} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1.3fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Permissions and duties" />
            <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2.5 px-4 py-3 text-sm">
              <dt className="text-ink-3">Employment</dt>
              <dd>{emp.employment_type === 'VENDOR' ? 'Vendor / processor (Art. 29 applies)' : 'Staff'} {emp.status === 'LEFT' && <Pill tone="crit">Left {emp.left_at?.slice(0, 10)}</Pill>}</dd>
              <dt className="text-ink-3">Shift</dt><dd className="tabular">{emp.shift_start.slice(0, 5)}–{emp.shift_end.slice(0, 5)}, {emp.work_days.map((d) => DAYS[d]).join(' ')}</dd>
              <dt className="text-ink-3">Max sensitivity</dt><dd>{emp.max_sensitivity}</dd>
              <dt className="text-ink-3">Data categories</dt>
              <dd className="flex flex-wrap gap-1">{emp.allowed_categories.length ? emp.allowed_categories.map((c) => <Pill key={c} tone="ok">{c}</Pill>) : <span className="text-ink-3">General business data only</span>}</dd>
              <dt className="text-ink-3">Windows accounts</dt>
              <dd className="font-mono text-xs">{emp.accounts.length ? emp.accounts.map((a) => <p key={a.id}>{a.account}</p>) : <span className="font-sans text-ink-3">none linked</span>}</dd>
              <dt className="text-ink-3">Laptops</dt>
              <dd className="space-y-1.5">{emp.devices?.length ? emp.devices.map((d) => <DeviceRow key={d.id} device={d} compact />) : <span className="text-ink-3">agent not installed</span>}</dd>
            </dl>
          </Card>
          <Card>
            <CardHeader icon={BrainCircuit} title="AI anomaly score, last 14 days" subtitle="60 = alert line" />
            <div className="h-48 px-2 py-3">
              {series.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={series}>
                    <defs><linearGradient id="ai" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={colors.accent} stopOpacity={0.3} /><stop offset="100%" stopColor={colors.accent} stopOpacity={0} /></linearGradient></defs>
                    <CartesianGrid vertical={false} stroke={colors.grid} />
                    <XAxis dataKey="day" tick={{ fill: colors.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 100]} tick={{ fill: colors.tick, fontSize: 11 }} axisLine={false} tickLine={false} width={28} />
                    <ReferenceLine y={60} stroke={colors.high} strokeDasharray="4 4" />
                    <Tooltip contentStyle={{ background: colors.panel, border: `1px solid ${colors.border}`, borderRadius: 8, fontSize: 12, color: colors.ink }} />
                    <Area type="monotone" dataKey="score" stroke={colors.accent} fill="url(#ai)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <Empty title="No activity scored yet" />}
            </div>
            {today && (
              <div className="border-t border-line px-4 py-3">
                <p className="mb-2 text-xs font-medium text-ink-3">Today, feature by feature (z = how far from typical)</p>
                <div className="space-y-1.5">
                  {today.contributions.map((c) => (
                    <div key={c.feature} className="grid grid-cols-[150px_1fr_70px] items-center gap-3 text-xs">
                      <span className="text-ink-2">{c.label}</span>
                      <div className="h-1.5 overflow-hidden rounded-full bg-line"><div className={c.z >= 2 ? 'h-full bg-high' : 'h-full bg-accent/60'} style={{ width: `${Math.min(100, c.z * 10)}%` }} /></div>
                      <span className="tabular text-right text-ink-3">{c.value} / {c.typical}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader icon={ShieldAlert} title="Incidents" subtitle={`${emp.incidents.length} most recent`}
              actions={<Link to={`/incidents?employee=${emp.id}&status=`} className="text-xs font-medium text-accent hover:underline">View all</Link>} />
            <div className="max-h-[440px] overflow-y-auto">
              {emp.incidents.length ? emp.incidents.map((i) => <IncidentRow key={i.id} incident={i} compact />) : <Empty title="No incidents for this employee" />}
            </div>
          </Card>
          <Card>
            <CardHeader title="Recent activity"
              actions={<Link to={`/activity?employee=${emp.id}`} className="text-xs font-medium text-accent hover:underline">View all</Link>} />
            <div className="max-h-[440px] overflow-y-auto">
              {emp.recent_events.length ? emp.recent_events.map((e) => <EventRow key={e.id} event={e} />) : <Empty title="No activity recorded" />}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
