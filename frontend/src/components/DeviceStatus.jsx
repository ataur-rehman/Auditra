import { Download, Laptop } from 'lucide-react'
import { ago } from '../lib/format'
import { Pill, cx } from './ui'

const STATE = {
  working: { tone: 'ok', label: 'Working', dot: 'bg-ok pulse-dot' },
  attention: { tone: 'warn', label: 'Needs attention', dot: 'bg-med' },
  offline: { tone: 'default', label: 'Offline', dot: 'bg-ink-3' },
}

/** Working / Needs attention / Offline, the same everywhere a laptop is shown. */
export function DeviceStatePill({ device }) {
  const s = STATE[device.state] || STATE.offline
  return (
    <Pill tone={s.tone}>
      <span className={cx('h-1.5 w-1.5 rounded-full', s.dot)} />
      {s.label}{device.state === 'offline' && device.last_seen ? ` · seen ${ago(device.last_seen)}` : ''}
    </Pill>
  )
}

/** One laptop: name, status, what is wrong, and when activity last arrived. */
export function DeviceRow({ device, compact }) {
  return (
    <div className={cx('flex flex-wrap items-start gap-x-3 gap-y-1', compact ? 'text-xs' : 'text-sm')}>
      <Laptop size={compact ? 13 : 16} className="mt-0.5 text-ink-3" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{device.hostname}</span>
          <DeviceStatePill device={device} />
        </div>
        {!compact && (
          <p className="mt-0.5 text-xs text-ink-3">
            Agent v{device.version} · last report {ago(device.last_seen)} · last activity recorded {ago(device.last_event)}
          </p>
        )}
        {device.problems?.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-[11px] text-med">{device.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
      </div>
    </div>
  )
}

export function DownloadAgentButton({ url, variant = 'secondary' }) {
  if (!url) return null
  const style = variant === 'primary'
    ? 'bg-accent text-on-accent hover:bg-accent-2 font-medium'
    : 'border border-line-2 bg-panel text-ink hover:bg-panel-2'
  return (
    // A new tab: the file normally just downloads; if the host (Google Drive) shows a page first, the console stays
    // open behind it.
    <a href={url} target="_blank" rel="noopener noreferrer"
      className={cx('inline-flex h-9 items-center gap-2 rounded-lg px-3.5 text-sm', style)}>
      <Download size={15} />Download AuditraAgent.exe
    </a>
  )
}
