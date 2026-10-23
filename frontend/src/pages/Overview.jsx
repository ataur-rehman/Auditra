import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity, ShieldCheck, Users } from 'lucide-react'
import api from '../lib/api'
import { useLive } from '../lib/live'
import { SEVERITY_HEX, SEVERITIES, article } from '../lib/format'
import { useThemeColors } from '../lib/theme'
import { EventRow, IncidentRow } from '../components/Feeds'
import { Card, CardHeader, Empty, PageHeader, Stat, cx } from '../components/ui'

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-card">
      <p className="mb-1 font-medium text-ink">{label}</p>
      {payload.filter((p) => p.value).map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 text-ink-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />{p.dataKey.toLowerCase()} <span className="tabular ml-auto pl-3 text-ink">{p.value}</span>
        </p>
      ))}
    </div>
  )
}

const level = (score) => (score >= 85 ? 'text-crit' : score >= 65 ? 'text-high' : score >= 40 ? 'text-med' : 'text-ink-3')

export default function Overview() {
  const { incidents, events, kpis, version } = useLive()
  const [data, setData] = useState(null)
  const colors = useThemeColors()
  const lastLoad = useRef(0)

  useEffect(() => {
    const wait = Math.max(0, 4000 - (Date.now() - lastLoad.current))
    const timer = setTimeout(() => {
      lastLoad.current = Date.now()
      api.get('/overview/').then((r) => setData(r.data)).catch(() => {})
    }, wait)
    return () => clearTimeout(timer)
  }, [version])

  const k = kpis || data?.kpis
  const feed = incidents.filter((i) => i.kind !== 'INDICATOR').slice(0, 7)
  const series = (data?.incidents_per_day || []).map((d) => ({ ...d, label: d.day.slice(8) }))

  return (
    <>
      <PageHeader title="Overview" subtitle="Potential GDPR violations on monitored machines, updated live." />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat to="/incidents" label="Open violations" value={k?.open_incidents} hint={`${k?.incidents_today ?? 0} detected today`} />
        <Stat to="/incidents?severity=CRITICAL" label="Critical" value={k?.critical_open} tone={k?.critical_open ? 'crit' : undefined} hint={`${k?.high_open ?? 0} high risk`} />
        <Stat to="/activity" label="Events today" value={k?.events_today} hint={`${k?.employees_monitored ?? 0} employees monitored`} />
        <Stat to="/admin/agents" label="Agents online" value={k ? `${k.agents_online} / ${k.agents_total}` : null} tone={k?.agents_online ? 'ok' : undefined}
          hint={k?.precision != null ? `officer precision ${k.precision}%` : 'no closed incidents yet'} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Live violations" subtitle="Newest first"
            actions={<Link to="/incidents" className="text-xs font-medium text-accent hover:underline">View all</Link>} />
          {feed.length ? feed.map((i) => <IncidentRow key={i.id} incident={i} />) : (
            <Empty icon={ShieldCheck} title="No potential violations">They appear here within seconds of the activity.</Empty>
          )}
        </Card>
        <Card>
          <CardHeader title="Activity" subtitle="Events received from agents"
            actions={<Link to="/activity" className="text-xs font-medium text-accent hover:underline">View all</Link>} />
          {events.length ? events.slice(0, 8).map((e) => <EventRow key={e.id} event={e} />) : (
            <Empty icon={Activity} title="Waiting for events" />
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Violations, last 14 days" />
          <div className="h-56 px-3 py-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={series} barSize={14}>
                <CartesianGrid vertical={false} stroke={colors.grid} />
                <XAxis dataKey="label" tick={{ fill: colors.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: colors.tick, fontSize: 11 }} axisLine={false} tickLine={false} width={24} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: colors.grid, opacity: 0.4 }} />
                {[...SEVERITIES].reverse().map((s, i) => (
                  <Bar key={s} dataKey={s} stackId="a" fill={SEVERITY_HEX[s]} radius={i === SEVERITIES.length - 1 ? [3, 3, 0, 0] : 0} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardHeader title="Top GDPR articles" />
          <div className="space-y-3 px-5 py-4">
            {data?.by_article?.length ? data.by_article.slice(0, 6).map((row) => (
              <div key={row.article} className="grid grid-cols-[64px_1fr_28px] items-center gap-3 text-xs">
                <span className="font-medium text-ink-2">{article(row.article)}</span>
                <div className="h-1.5 overflow-hidden rounded-full bg-line">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${(row.count / data.by_article[0].count) * 100}%` }} />
                </div>
                <span className="tabular text-right text-ink-2">{row.count}</span>
              </div>
            )) : <Empty title="No data yet" />}
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="Employee risk" subtitle="Highest open score and today's AI score"
          actions={<Link to="/employees" className="text-xs font-medium text-accent hover:underline">Directory</Link>} />
        {data?.employees?.length ? data.employees.map((e) => (
          <Link key={e.id} to={`/employees/${e.id}`}
            className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-8 border-b border-line px-5 py-3 text-sm last:border-0 hover:bg-panel-2">
            <div className="min-w-0">
              <p className="truncate font-medium text-ink">{e.full_name}</p>
              <p className="truncate text-xs text-ink-3">{e.role} · {e.department}{e.repeat_offender ? ' · Art. 83 escalation' : ''}</p>
            </div>
            <div className="text-right"><p className="tabular font-semibold text-ink">{e.open_incidents}</p><p className="text-[11px] text-ink-3">open</p></div>
            <div className="text-right"><p className={cx('tabular font-semibold', level(e.risk_score))}>{e.risk_score}</p><p className="text-[11px] text-ink-3">risk</p></div>
            <div className="w-12 text-right"><p className={cx('tabular font-semibold', e.ai_score_today >= 60 ? 'text-high' : 'text-ink-2')}>{e.ai_score_today != null ? Math.round(e.ai_score_today) : '—'}</p><p className="text-[11px] text-ink-3">AI</p></div>
          </Link>
        )) : <Empty icon={Users} title="No employees yet">An administrator adds them under Employees &amp; Access.</Empty>}
      </Card>
    </>
  )
}
