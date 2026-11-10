import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Download, FolderDown, KeyRound, Laptop, LogOut, Moon, ShieldCheck, Sun } from 'lucide-react'
import api, { errorText } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useTheme } from '../lib/theme'
import { full } from '../lib/format'
import EventIcon from '../components/EventIcon'
import { DeviceRow, DownloadAgentButton } from '../components/DeviceStatus'
import { Button, Card, CardHeader, Empty, ErrorNote, Pill, Spinner, cx } from '../components/ui'

const EVENT_LABELS = {
  LOGON: 'Sign-ins', UNLOCK: 'Unlocks', LOCK: 'Locks', LOGON_FAILED: 'Failed sign-ins', ACCOUNT_LOCKED: 'Account lockouts',
  FILE_READ: 'Files opened', FILE_WRITE: 'Files changed', FILE_DELETE: 'Files deleted', FILE_COPY_TO_USB: 'Files copied to USB',
  USB_CONNECTED: 'USB storage connected', PRINT: 'Documents printed', WEB_VISIT: 'Watched site visits',
  ACCOUNT_CREATED: 'Accounts created', GROUP_MEMBER_ADDED: 'Group changes', AUDIT_POLICY_CHANGED: 'Audit policy changes',
  TASK_CREATED: 'Scheduled tasks created', LOG_CLEARED: 'Security log cleared', RETENTION_EXCEEDED: 'Files past retention',
}

function Step({ number, done, title, children }) {
  return (
    <Card>
      <div className="flex gap-4 px-5 py-4">
        <div className={cx('flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          done ? 'bg-ok/15 text-ok' : 'bg-accent/10 text-accent')}>
          {done ? <CheckCircle2 size={16} /> : number}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="mt-2 text-sm text-ink-2">{children}</div>
        </div>
      </div>
    </Card>
  )
}

/** The first thing an employee sees: is monitoring set up on my laptop, and is it working? */
function AgentBanner({ devices, downloadUrl, acknowledged }) {
  const working = devices.filter((d) => d.state === 'working')
  const attention = devices.filter((d) => d.state === 'attention')
  let tone, icon, title, text
  if (!devices.length) {
    tone = 'border-accent/40 bg-accent/5'; icon = <Download size={18} className="text-accent" />
    title = 'The Auditra agent is not installed yet'
    text = acknowledged ? 'Download it below, run it on your work laptop and enter your enrolment code.'
      : 'Read the monitoring notice, then download the agent and enrol your laptop.'
  } else if (attention.length) {
    tone = 'border-med/40 bg-med/5'; icon = <AlertTriangle size={18} className="text-med" />
    title = `Installed on ${attention.map((d) => d.hostname).join(', ')}, but it needs attention`
    text = attention.flatMap((d) => d.problems).join(' · ') + '. Your administrator sees this too.'
  } else if (working.length) {
    tone = 'border-ok/40 bg-ok/5'; icon = <CheckCircle2 size={18} className="text-ok" />
    title = `Installed and working on ${working.map((d) => d.hostname).join(', ')}`
    text = 'The agent is running and reporting to Auditra.'
  } else {
    tone = 'border-line bg-panel'; icon = <Laptop size={18} className="text-ink-3" />
    title = `Installed on ${devices.map((d) => d.hostname).join(', ')}, currently offline`
    text = 'The laptop is switched off or has no internet. Activity is kept on the laptop and sent when it is back.'
  }
  return (
    <div className={cx('flex flex-wrap items-center gap-3 rounded-xl border px-5 py-4', tone)}>
      {icon}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="mt-0.5 text-xs text-ink-2">{text}</p>
      </div>
      {!devices.length && acknowledged && <DownloadAgentButton url={downloadUrl} variant="primary" />}
    </div>
  )
}

function Countdown({ until }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const left = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000))
  if (!left) return <span className="text-crit">expired, get a new code</span>
  return <span className="tabular">valid for {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}</span>
}

export default function EmployeePortal() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [code, setCode] = useState(null)

  const load = useCallback(() => api.get('/me/portal/').then((r) => setData(r.data)).catch((e) => setError(errorText(e))), [])
  useEffect(() => { load() }, [load])
  // Devices come online a few seconds after the installer finishes; refresh while the page is open.
  useEffect(() => {
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  async function acknowledge() {
    setBusy('ack'); setError('')
    try { await api.post('/me/notice/ack/'); await load() } catch (e) { setError(errorText(e)) } finally { setBusy('') }
  }

  async function getCode() {
    setBusy('code'); setError('')
    try { const r = await api.post('/me/enrolment-codes/'); setCode(r.data) } catch (e) { setError(errorText(e)) } finally { setBusy('') }
  }

  if (!data) return error ? <div className="p-8"><ErrorNote>{error}</ErrorNote></div> : <Spinner label="Loading your portal" />
  const { notice, employee, dpo, devices } = data
  const enrolled = devices.length > 0

  return (
    <div className="min-h-full bg-canvas">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Auditra</p>
            <p className="truncate text-[11px] text-ink-3">{data.organisation || 'Employee portal'}</p>
          </div>
          <span className="hidden text-xs text-ink-3 sm:inline">{user?.name}</span>
          <button title={theme === 'dark' ? 'Light mode' : 'Dark mode'} onClick={toggle}
            className="rounded-md p-1.5 text-ink-3 hover:bg-panel-2 hover:text-ink">
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button title="Sign out" onClick={async () => { await logout(); navigate('/login') }}
            className="rounded-md p-1.5 text-ink-3 hover:bg-panel-2 hover:text-ink">
            <LogOut size={15} />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Hello, {employee.full_name}</h1>
          <p className="mt-1 text-sm text-ink-3">
            {employee.department} · {employee.role} · shift {String(employee.shift_start).slice(0, 5)}–{String(employee.shift_end).slice(0, 5)}
          </p>
        </div>
        <ErrorNote>{error}</ErrorNote>

        <AgentBanner devices={devices} downloadUrl={data.download_url} acknowledged={data.acknowledged} />

        <Step number={1} done={data.acknowledged} title="Read the monitoring notice">
          <p>{notice.purpose}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Recorded on your laptop</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[13px]">{notice.collected.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Never recorded</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[13px]">{notice.not_collected.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
          </div>
          <dl className="mt-3 space-y-1 text-[13px]">
            <div><dt className="inline font-medium text-ink">Lawful basis: </dt><dd className="inline">{notice.lawful_basis}</dd></div>
            <div><dt className="inline font-medium text-ink">Retention: </dt><dd className="inline">{notice.retention}</dd></div>
            <div><dt className="inline font-medium text-ink">Data Protection Officer: </dt>
              <dd className="inline">{dpo ? [dpo.name, dpo.contact].filter(Boolean).join(', ') : 'not designated yet'}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-ink-3">
            Acknowledging confirms you have read this notice. It is not consent and does not switch monitoring on or off.
            You can ask the DPO for a copy of the data recorded about you (Art. 15).
          </p>
          <div className="mt-3">
            {data.acknowledged
              ? <Pill tone="ok">Acknowledged {full(data.acknowledged_at)} (version {notice.version})</Pill>
              : <Button variant="primary" icon={ShieldCheck} loading={busy === 'ack'} onClick={acknowledge}>I have read the notice</Button>}
          </div>
        </Step>

        <Step number={2} done={enrolled} title="Download the Auditra agent">
          <p>Run <span className="font-mono text-[13px]">AuditraAgent.exe</span> on your work laptop. Windows asks for administrator
            approval: Auditra needs it to switch on Windows auditing. If your account is not an administrator, ask IT to approve it.</p>
          <div className="mt-3">
            <DownloadAgentButton url={data.download_url} variant={data.acknowledged && !enrolled ? 'primary' : 'secondary'} />
          </div>
          <div className="mt-4 rounded-lg border border-line bg-panel-2/50 px-4 py-3 text-[13px]">
            <p className="font-medium text-ink">Trying Auditra out? Get the test company folder</p>
            <p className="mt-1 text-ink-2">
              <span className="font-mono">C:\AuditraCompany</span> holds sample Finance, Payroll, HR, Medical, Legal, Customers and
              Biometrics files that the organisation's data catalogue already covers. Opening, copying to USB, printing or deleting
              them creates real events. Either tick <span className="font-medium">Also create the test company folder</span> in the
              agent's setup window, or download the folder and extract it into <span className="font-mono">C:\</span>.
            </p>
            <a href="/AuditraCompany-test.zip" download className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-2 bg-panel px-3 text-xs text-ink hover:bg-panel-2">
              <FolderDown size={14} />Download test folder (zip)
            </a>
          </div>
        </Step>

        <Step number={3} done={enrolled} title="Enrol your laptop">
          <p>The setup window asks for a one-time code. It links the laptop to you and works once.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button variant={data.acknowledged ? 'primary' : 'secondary'} icon={KeyRound} disabled={!data.acknowledged}
              loading={busy === 'code'} onClick={getCode}>{code ? 'Get a new code' : 'Get enrolment code'}</Button>
            {!data.acknowledged && <span className="text-xs text-ink-3">Acknowledge the notice first.</span>}
            {code && (
              <div className="flex items-center gap-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-2">
                <span className="select-all font-mono text-xl font-semibold tracking-[0.2em] text-ink">{code.code}</span>
                <span className="text-xs text-ink-3"><Countdown until={code.expires_at} /></span>
              </div>
            )}
          </div>
        </Step>

        <Card>
          <CardHeader title="My devices" subtitle="Laptops enrolled to you. This page refreshes every 10 seconds." />
          {devices.length ? devices.map((d) => (
            <div key={d.id} className="border-b border-line/70 px-5 py-3 last:border-0"><DeviceRow device={d} /></div>
          )) : <Empty icon={Laptop} title="No laptop enrolled yet">Follow the steps above.</Empty>}
        </Card>

        <Card>
          <CardHeader title="Recorded about you in the last 7 days" subtitle="Counts only. Officers review possible violations; most activity is normal work." />
          {data.collected_7_days.length ? (
            <div className="grid gap-px bg-line sm:grid-cols-2">
              {data.collected_7_days.map((row) => (
                <div key={row.event_type} className="flex items-center gap-2.5 bg-panel px-5 py-2.5 text-sm">
                  <EventIcon type={row.event_type} className="text-ink-3" />
                  <span className="flex-1">{EVENT_LABELS[row.event_type] || row.event_type}</span>
                  <span className="tabular font-medium">{row.count}</span>
                </div>
              ))}
            </div>
          ) : <Empty title="Nothing recorded yet" />}
        </Card>
      </main>
    </div>
  )
}
