import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Lock, Moon, ShieldCheck, Sun } from 'lucide-react'
import { useTheme } from '../lib/theme'
import { Button, ErrorNote, Field, Input } from '../components/ui'
import { useAuth } from '../lib/auth'
import { errorText } from '../lib/api'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={user.role === 'employee' ? '/me' : '/'} replace />

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const me = await login(username, password)
      navigate(me.role === 'employee' ? '/me' : '/')
    } catch (err) {
      setError(err?.response?.status === 401 ? 'Wrong username or password.' : errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden border-r border-line bg-panel lg:block">
        <div className="absolute inset-0 opacity-40"
          style={{ backgroundImage: 'radial-gradient(circle at 20% 20%, rgba(56,189,248,.18), transparent 45%), radial-gradient(circle at 80% 70%, rgba(240,68,56,.12), transparent 40%)' }} />
        <div className="relative flex h-full flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="" className="h-10 w-10" />
            <span className="text-lg font-semibold">Auditra</span>
          </div>
          <div className="max-w-lg">
            <h1 className="text-3xl font-semibold leading-tight tracking-tight">
              Real-time GDPR compliance monitoring for every endpoint.
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-ink-2">
              Windows activity is mapped to the GDPR articles it may breach, scored with a transparent rule
              model and an anomaly model trained on the CERT insider-threat dataset, and handed to the compliance
              officer with the evidence.
            </p>
            <div className="mt-8 grid grid-cols-3 gap-3 text-xs">
              {[['22', 'GDPR articles'], ['41', 'detection rules'], ['< 10 s', 'event to alert']].map(([v, l]) => (
                <div key={l} className="rounded-lg border border-line bg-canvas/50 px-3 py-3">
                  <p className="text-lg font-semibold text-accent">{v}</p>
                  <p className="text-ink-3">{l}</p>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs text-ink-3">Findings are potential violations and risk indicators, not legal determinations.</p>
        </div>
      </div>
      <div className="relative flex items-center justify-center p-6">
        <button onClick={toggle} title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
          className="absolute right-5 top-5 rounded-lg border border-line bg-panel p-2 text-ink-3 hover:text-ink">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div className="mb-6">
            <div className="mb-4 inline-flex rounded-xl border border-line bg-panel p-2.5"><ShieldCheck size={22} className="text-accent" /></div>
            <h2 className="text-xl font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-ink-3">Compliance officers, administrators, and employees enrolling their laptop.</p>
          </div>
          <Field label="Username">
            <Input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
          <ErrorNote>{error}</ErrorNote>
          <Button type="submit" variant="primary" className="w-full" loading={busy} icon={Lock}>Sign in</Button>
        </form>
      </div>
    </div>
  )
}
