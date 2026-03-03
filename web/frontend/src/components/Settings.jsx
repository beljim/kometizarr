import { useState, useEffect, useRef } from 'react'

// ── Cron helpers ──────────────────────────────────────────────────────────────

function parseCron(expr) {
  if (!expr) return { freq: 'daily', hour: 3, minute: 0, weekday: '0' }
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return { freq: 'custom', hour: 3, minute: 0, weekday: '0' }
  const [min, hr, , , dow] = parts
  if (hr === '*') return { freq: 'hourly', hour: 0, minute: 0, weekday: '0' }
  if (dow === '*') return { freq: 'daily', hour: parseInt(hr) || 0, minute: parseInt(min) || 0, weekday: '0' }
  return { freq: 'weekly', hour: parseInt(hr) || 0, minute: parseInt(min) || 0, weekday: dow }
}

function buildCron({ freq, hour, minute, weekday }) {
  const h = parseInt(hour) || 0
  const m = parseInt(minute) || 0
  if (freq === 'hourly') return '0 * * * *'
  if (freq === 'daily') return `${m} ${h} * * *`
  if (freq === 'weekly') return `${m} ${h} * * ${weekday}`
  return null
}

const DAYS = [
  { value: '0', label: 'Sunday' }, { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' }, { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' }, { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
]

// ── Toggle switch ─────────────────────────────────────────────────────────────

function Toggle({ checked, onChange, color = 'blue' }) {
  const bg = checked
    ? (color === 'purple' ? 'bg-purple-600' : 'bg-blue-600')
    : 'bg-gray-600'
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${bg}`}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${checked ? 'translate-x-5' : 'translate-x-0'}`}
      />
    </button>
  )
}

// ── Warning / Confirm ─────────────────────────────────────────────────────────

function WarningBox({ children }) {
  return (
    <div className="mt-2 p-3 bg-yellow-900/40 border border-yellow-700/60 rounded text-xs text-yellow-300 leading-relaxed">
      ⚠️ {children}
    </div>
  )
}

function ConfirmModal({ title, warning, confirmLabel, onConfirm, onCancel, requireTyped }) {
  const [typed, setTyped] = useState('')
  const inputRef = useRef(null)
  useEffect(() => { if (requireTyped && inputRef.current) inputRef.current.focus() }, [requireTyped])
  const ready = requireTyped ? typed === requireTyped : true
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={onCancel}>
      <div className="bg-gray-900 border border-red-700 rounded-xl p-6 max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
        <h3 className="text-white font-semibold text-lg mb-3">{title}</h3>
        <div className="p-3 bg-red-900/40 border border-red-700/60 rounded text-sm text-red-300 leading-relaxed mb-4">
          ⚠️ {warning}
        </div>
        {requireTyped && (
          <div className="mb-4">
            <p className="text-gray-400 text-sm mb-1">Type <span className="font-mono text-white">{requireTyped}</span> to confirm:</p>
            <input ref={inputRef} type="text" value={typed} onChange={e => setTyped(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-white text-sm font-mono"
              placeholder={requireTyped} />
          </div>
        )}
        <div className="flex gap-3">
          <button onClick={onCancel} className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white transition">
            Cancel
          </button>
          <button onClick={() => ready && onConfirm()} disabled={!ready}
            className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-700 disabled:cursor-not-allowed rounded text-sm text-white font-semibold transition">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Cron card ─────────────────────────────────────────────────────────────────

function CronCard({ label, desc, color, cron, libraries, onChange }) {
  const initialParsed = parseCron(cron.schedule)
  const [showAdvanced, setShowAdvanced] = useState(initialParsed.freq === 'custom')
  const [customExpr, setCustomExpr] = useState(cron.schedule || '')

  const parsed = parseCron(cron.schedule)
  const timeValue = `${String(parsed.hour).padStart(2, '0')}:${String(parsed.minute).padStart(2, '0')}`

  const update = (patch) => {
    const newParsed = { ...parsed, ...patch }
    const newSchedule = buildCron(newParsed) || cron.schedule
    onChange({ ...cron, schedule: newSchedule })
  }

  const borderColor = cron.enabled
    ? (color === 'purple' ? 'border-purple-800/60' : 'border-blue-800/60')
    : 'border-gray-700'

  return (
    <div className={`bg-gray-900 border ${borderColor} rounded-xl p-5 transition-colors`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-white">{label}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
        </div>
        <Toggle checked={cron.enabled || false} onChange={v => onChange({ ...cron, enabled: v })} color={color} />
      </div>

      {cron.enabled && (
        <div className="mt-4 space-y-3">
          {/* Library checkboxes */}
          <div>
            <label className="text-xs text-gray-400 block mb-1.5">
              Libraries <span className="text-gray-600">(none selected = all)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {libraries.map(lib => {
                const checked = (cron.libraries || []).includes(lib.name)
                return (
                  <button
                    key={lib.name}
                    type="button"
                    onClick={() => {
                      const libs = cron.libraries || []
                      const next = checked ? libs.filter(l => l !== lib.name) : [...libs, lib.name]
                      onChange({ ...cron, libraries: next })
                    }}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
                      checked
                        ? (color === 'purple'
                            ? 'bg-purple-700/60 border-purple-500 text-purple-200'
                            : 'bg-blue-700/60 border-blue-500 text-blue-200')
                        : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-gray-500'
                    }`}
                  >
                    {checked ? '✓ ' : ''}{lib.name}
                  </button>
                )
              })}
              {libraries.length === 0 && <span className="text-xs text-gray-500">No libraries loaded</span>}
            </div>
            {(cron.libraries || []).length === 0 && (
              <p className="text-xs text-gray-600 mt-1">All libraries will be processed</p>
            )}
          </div>

          {/* Schedule: simple or advanced */}
          {!showAdvanced ? (
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={parsed.freq}
                onChange={e => update({ freq: e.target.value })}
                className="px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="hourly">Every hour</option>
              </select>

              {parsed.freq === 'weekly' && (
                <>
                  <span className="text-gray-400 text-sm">on</span>
                  <select
                    value={parsed.weekday}
                    onChange={e => update({ weekday: e.target.value })}
                    className="px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                  >
                    {DAYS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </>
              )}

              {parsed.freq !== 'hourly' && (
                <>
                  <span className="text-gray-400 text-sm">at</span>
                  <input
                    type="time"
                    value={timeValue}
                    onChange={e => {
                      const [h, m] = e.target.value.split(':').map(Number)
                      update({ hour: h, minute: m })
                    }}
                    className="px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                  />
                </>
              )}
            </div>
          ) : (
            <div>
              <input
                type="text"
                value={customExpr}
                onChange={e => {
                  setCustomExpr(e.target.value)
                  onChange({ ...cron, schedule: e.target.value })
                }}
                placeholder="0 3 * * *  (min hour day month weekday)"
                className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white font-mono"
              />
            </div>
          )}

          {/* Footer: advanced toggle + next run */}
          <div className="flex items-center justify-between pt-1">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-xs text-gray-600 hover:text-gray-400 transition"
            >
              {showAdvanced ? '← Simple mode' : 'Advanced (cron expression)'}
            </button>
            {cron.next_run && (
              <p className="text-xs text-gray-500">
                Next: <span className={color === 'purple' ? 'text-purple-400' : 'text-blue-400'}>
                  {new Date(cron.next_run).toLocaleString()}
                </span>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Settings component ───────────────────────────────────────────────────

export default function Settings() {
  const [libraries, setLibraries] = useState([])
  const [settings, setSettings] = useState(null)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')

  // Fresh posters
  const [freshLib, setFreshLib] = useState('')
  const [freshStatus, setFreshStatus] = useState(null)
  const [showFreshConfirm, setShowFreshConfirm] = useState(false)

  // Delete backups
  const [deleteLib, setDeleteLib] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteResult, setDeleteResult] = useState(null)

  // Health
  const [health, setHealth] = useState(null)
  const [healthLoading, setHealthLoading] = useState(true)

  // Poll fresh posters status while running
  useEffect(() => {
    let interval
    if (freshStatus?.is_running) {
      interval = setInterval(async () => {
        const res = await fetch('/api/fetch-fresh-posters/status')
        const data = await res.json()
        setFreshStatus(data)
      }, 1000)
    }
    return () => clearInterval(interval)
  }, [freshStatus?.is_running])

  useEffect(() => {
    fetch('/api/libraries').then(r => r.json()).then(d => setLibraries(d.libraries || []))
    fetch('/api/settings').then(r => r.json()).then(data => {
      setSettings(data)
    })
    fetch('/api/health').then(r => r.json()).then(d => {
      setHealth(d)
      setHealthLoading(false)
    }).catch(() => setHealthLoading(false))
  }, [])

  const saveSettings = async (patch) => {
    setSaving(true)
    const merged = { ...settings, ...patch }
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(merged),
    })
    const data = await res.json()
    setSettings({
      ...merged,
      cron_normal: { ...merged.cron_normal, next_run: data.cron_normal_next_run },
      cron_force: { ...merged.cron_force, next_run: data.cron_force_next_run },
    })
    setSaving(false)
    setSavedMsg('Saved!')
    setTimeout(() => setSavedMsg(''), 2000)
  }

  const startFreshPosters = async () => {
    setShowFreshConfirm(false)
    const res = await fetch('/api/fetch-fresh-posters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ library_name: freshLib }),
    })
    const data = await res.json()
    if (data.status === 'started') {
      setFreshStatus({ is_running: true, library: freshLib, progress: 0, total: 0, restored: 0, failed: 0, current_item: null })
    }
  }

  const deleteBackups = async () => {
    setShowDeleteConfirm(false)
    const res = await fetch(`/api/backups?library_name=${encodeURIComponent(deleteLib)}&confirm=DELETE`, { method: 'DELETE' })
    const data = await res.json()
    setDeleteResult(data)
  }

  const webhookUrl = `${window.location.protocol}//${window.location.host}/webhook/plex`
  const [copied, setCopied] = useState(false)
  const copyWebhookUrl = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(webhookUrl)
    } else {
      const el = document.createElement('textarea')
      el.value = webhookUrl
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (!settings) return <div className="text-gray-400 text-center py-12">Loading settings…</div>

  return (
    <div className="max-w-2xl mx-auto space-y-8">

      {/* ── Health Dashboard ──────────────────────────────────────── */}
      <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
        <h2 className="text-white font-semibold text-base">💚 System Health</h2>
        {healthLoading ? (
          <p className="text-gray-400 text-xs">Checking…</p>
        ) : health ? (
          <div className="grid grid-cols-2 gap-3 text-sm">
            {/* Plex */}
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${health.plex_connected ? 'bg-green-400' : 'bg-red-400'}`} />
              <span className="text-gray-300 text-xs">Plex</span>
            </div>
            <span className={`text-xs ${health.plex_connected ? 'text-green-400' : 'text-red-400'}`}>
              {health.plex_connected ? 'Connected' : 'Disconnected'}
            </span>

            {/* API keys */}
            {health.api_keys && Object.entries(health.api_keys).map(([key, status]) => (
              <div key={key} className="contents">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${status === 'valid' ? 'bg-green-400' : status === 'not_set' ? 'bg-gray-500' : 'bg-yellow-400'}`} />
                  <span className="text-gray-300 text-xs">{key.toUpperCase()}</span>
                </div>
                <span className={`text-xs ${status === 'valid' ? 'text-green-400' : status === 'not_set' ? 'text-gray-500' : 'text-yellow-400'}`}>
                  {status === 'valid' ? 'Valid' : status === 'not_set' ? 'Not set' : status}
                </span>
              </div>
            ))}

            {/* Backup disk */}
            {health.backup_disk && (
              <>
                <span className="text-gray-300 text-xs">Backup disk</span>
                <span className="text-gray-400 text-xs">{health.backup_disk.total_size} ({health.backup_disk.file_count} files)</span>
              </>
            )}

            {/* Last run */}
            {health.last_run && (
              <>
                <span className="text-gray-300 text-xs">Last run</span>
                <span className="text-gray-400 text-xs">{new Date(health.last_run.timestamp).toLocaleString()} — {health.last_run.library}</span>
              </>
            )}

            {/* Next scheduled */}
            {health.next_scheduled && health.next_scheduled.length > 0 && (
              <>
                <span className="text-gray-300 text-xs">Next scheduled</span>
                <span className="text-gray-400 text-xs">
                  {health.next_scheduled.map(s => `${s.name}: ${new Date(s.next_run).toLocaleString()}`).join(' · ')}
                </span>
              </>
            )}
          </div>
        ) : (
          <p className="text-gray-500 text-xs">Health data unavailable</p>
        )}
      </section>

      {/* ── Scheduled Processing ──────────────────────────────────── */}
      <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
        <div>
          <h2 className="text-white font-semibold text-base">🕐 Scheduled Processing</h2>
          <p className="text-xs text-gray-400 mt-1">Two independent schedules — one for new items, one to refresh ratings on everything.</p>
        </div>

        <CronCard
          label="Normal run"
          desc="Processes new items only (skips already overlaid posters)"
          color="blue"
          cron={settings.cron_normal || {}}
          libraries={libraries}
          onChange={val => setSettings(s => ({ ...s, cron_normal: val }))}
        />

        <CronCard
          label="Force run"
          desc="Re-processes everything — refreshes ratings on all posters"
          color="purple"
          cron={settings.cron_force || {}}
          libraries={libraries}
          onChange={val => setSettings(s => ({ ...s, cron_force: val }))}
        />

        <div className="flex items-center gap-3 pt-2">
          <button onClick={() => saveSettings({})} disabled={saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 rounded text-sm text-white font-semibold transition">
            {saving ? 'Saving…' : 'Save Schedule'}
          </button>
          {savedMsg && <span className="text-xs text-green-400">{savedMsg}</span>}
        </div>
      </section>

      {/* ── Plex Webhook ──────────────────────────────────────────── */}
      <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
        <h2 className="text-white font-semibold text-base">🔗 Plex Webhook</h2>
        <p className="text-xs text-gray-400">
          Automatically trigger processing when new items are added to Plex.
          Add the URL below to <strong className="text-gray-300">Plex → Settings → Webhooks</strong>.
        </p>

        <div>
          <label className="text-xs text-gray-400 block mb-1">Webhook URL (copy into Plex)</label>
          <div className="flex gap-2">
            <input readOnly value={webhookUrl}
              className="flex-1 px-3 py-1.5 bg-gray-900 border border-gray-700 rounded text-sm text-gray-300 font-mono" />
            <button onClick={copyWebhookUrl}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white transition min-w-[2.5rem]">
              {copied ? '✓' : '📋'}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-white">Enable webhook processing</p>
            <p className="text-xs text-gray-500 mt-0.5">Trigger overlay processing when new items are added</p>
          </div>
          <Toggle
            checked={settings.webhook?.enabled || false}
            onChange={v => setSettings(s => ({ ...s, webhook: { ...s.webhook, enabled: v } }))}
          />
        </div>

        {settings.webhook?.enabled && (
          <div>
            <label className="text-xs text-gray-400 block mb-1.5">
              Libraries <span className="text-gray-600">(none selected = all)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {libraries.map(lib => {
                const checked = (settings.webhook?.libraries || []).includes(lib.name)
                return (
                  <button
                    key={lib.name}
                    type="button"
                    onClick={() => {
                      const libs = settings.webhook?.libraries || []
                      const next = checked ? libs.filter(l => l !== lib.name) : [...libs, lib.name]
                      setSettings(s => ({ ...s, webhook: { ...s.webhook, libraries: next } }))
                    }}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
                      checked
                        ? 'bg-blue-700/60 border-blue-500 text-blue-200'
                        : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-gray-500'
                    }`}
                  >
                    {checked ? '✓ ' : ''}{lib.name}
                  </button>
                )
              })}
              {libraries.length === 0 && <span className="text-xs text-gray-500">No libraries loaded</span>}
            </div>
            {(settings.webhook?.libraries || []).length === 0 && (
              <p className="text-xs text-gray-600 mt-1">All libraries will be monitored</p>
            )}
          </div>
        )}

        <button onClick={() => saveSettings({ webhook: settings.webhook })} disabled={saving}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 rounded text-sm text-white font-semibold transition">
          {saving ? 'Saving…' : 'Save Webhook Settings'}
        </button>
        {savedMsg && <span className="text-xs text-green-400 ml-3">{savedMsg}</span>}

        {/* Webhook delay */}
        {settings.webhook?.enabled && (
          <div className="mt-4 pt-4 border-t border-gray-700">
            <label className="text-xs text-gray-400 block mb-1">
              Webhook Delay: <span className="text-white font-medium">{settings.webhook_delay ?? 15}s</span>
            </label>
            <p className="text-xs text-gray-500 mb-2">Seconds to wait after webhook before processing (allows Plex metadata to settle)</p>
            <input
              type="range" min="0" max="120" step="5"
              value={settings.webhook_delay ?? 15}
              onChange={e => setSettings(s => ({ ...s, webhook_delay: parseInt(e.target.value) }))}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
              <span>0s</span><span>30s</span><span>60s</span><span>90s</span><span>120s</span>
            </div>
            <button
              onClick={() => saveSettings({ webhook_delay: settings.webhook_delay })}
              disabled={saving}
              className="mt-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 rounded text-xs text-white font-semibold transition"
            >
              {saving ? 'Saving…' : 'Save Delay'}
            </button>
          </div>
        )}
      </section>

      {/* ── Library Maintenance ───────────────────────────────────── */}
      <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-6">
        <h2 className="text-white font-semibold text-base">🔧 Library Maintenance</h2>

        {/* Fetch Fresh Posters */}
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-2">Fetch Fresh Posters</h3>
          <p className="text-xs text-gray-400 mb-3">
            Resets each item's active poster to the original TMDB/agent poster, removing uploaded overlays from Plex's view.
            Does not delete backups.
          </p>
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-400 block mb-1">Library</label>
              <select value={freshLib} onChange={e => setFreshLib(e.target.value)}
                className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-sm text-white">
                <option value="">Select library…</option>
                {libraries.map(lib => <option key={lib.name} value={lib.name}>{lib.name}</option>)}
              </select>
            </div>
            <button onClick={() => setShowFreshConfirm(true)} disabled={!freshLib || freshStatus?.is_running}
              className="px-4 py-1.5 bg-amber-600 hover:bg-amber-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white text-sm font-semibold rounded transition">
              {freshStatus?.is_running ? '⏳ Running…' : '↺ Fetch Fresh Posters'}
            </button>
          </div>

          {freshStatus?.is_running && (
            <div className="mt-3 space-y-1">
              <div className="flex justify-between text-xs text-gray-400">
                <span>{freshStatus.current_item || '…'}</span>
                <span>{freshStatus.progress}/{freshStatus.total}</span>
              </div>
              <div className="w-full bg-gray-700 rounded-full h-1.5">
                <div className="bg-amber-500 h-1.5 rounded-full transition-all"
                  style={{ width: freshStatus.total ? `${(freshStatus.progress / freshStatus.total) * 100}%` : '0%' }} />
              </div>
            </div>
          )}

          {freshStatus && !freshStatus.is_running && freshStatus.total > 0 && (
            <p className="text-xs text-green-400 mt-2">✓ Done — {freshStatus.restored} reset, {freshStatus.failed} failed</p>
          )}

          <WarningBox>
            Fetching fresh posters while backups are present will cause Kometizarr to skip those items on the next run
            (it treats items with backups as already processed). Only use this in case of problems, and always combine with
            <strong className="text-yellow-200"> Delete Backups</strong>.
          </WarningBox>
        </div>

        <hr className="border-gray-700" />

        {/* Delete Backups */}
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-2">Delete Backups</h3>
          <p className="text-xs text-gray-400 mb-3">
            Permanently deletes all backed-up original posters for the selected library.
          </p>
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-400 block mb-1">Library</label>
              <select value={deleteLib} onChange={e => { setDeleteLib(e.target.value); setDeleteResult(null) }}
                className="w-full px-2 py-1.5 bg-gray-900 border border-gray-700 rounded text-sm text-white">
                <option value="">Select library…</option>
                {libraries.map(lib => <option key={lib.name} value={lib.name}>{lib.name}</option>)}
              </select>
            </div>
            <button onClick={() => setShowDeleteConfirm(true)} disabled={!deleteLib}
              className="px-4 py-1.5 bg-red-700 hover:bg-red-600 disabled:bg-gray-700 disabled:cursor-not-allowed text-white text-sm font-semibold rounded transition">
              🗑 Delete Backups
            </button>
          </div>

          {deleteResult && (
            <p className={`text-xs mt-2 ${deleteResult.error ? 'text-red-400' : 'text-green-400'}`}>
              {deleteResult.error ? `✗ ${deleteResult.error}` : `✓ Deleted ${deleteResult.items} backup(s)`}
            </p>
          )}

          <WarningBox>
            Deleting backups while overlays are active on your posters will cause <strong className="text-yellow-200">double overlays</strong> if
            you re-process without fetching fresh posters first. Only use this in case of problems, and always combine with
            <strong className="text-yellow-200"> Fetch Fresh Posters</strong>.
          </WarningBox>
        </div>
      </section>

      {/* Confirmation modals */}
      {showFreshConfirm && (
        <ConfirmModal
          title={`Fetch Fresh Posters — ${freshLib}`}
          warning="Fetching fresh posters while backups are present will cause Kometizarr to skip those items on the next run. Only use this in case of problems, and always combine with Delete Backups. Proceed anyway?"
          confirmLabel="Fetch Fresh Posters"
          onConfirm={startFreshPosters}
          onCancel={() => setShowFreshConfirm(false)}
        />
      )}

      {showDeleteConfirm && (
        <ConfirmModal
          title={`Delete Backups — ${deleteLib}`}
          warning="Deleting backups while overlays are active will cause double overlays if you re-process without fetching fresh posters first. Only use this in case of problems, and always combine with Fetch Fresh Posters. Proceed anyway?"
          confirmLabel="Delete Backups"
          requireTyped="DELETE"
          onConfirm={deleteBackups}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}
    </div>
  )
}
