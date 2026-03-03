import { useState, useEffect } from 'react'

export default function History() {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)

  const fetchHistory = async () => {
    try {
      const res = await fetch('/api/history?limit=100')
      const data = await res.json()
      setHistory((data.history || []).reverse())
    } catch (e) {
      console.error('Failed to load history:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchHistory() }, [])

  const clearHistory = async () => {
    await fetch('/api/history', { method: 'DELETE' })
    setHistory([])
  }

  const fmtDuration = (s) => {
    if (s < 60) return `${Math.round(s)}s`
    const m = Math.floor(s / 60)
    const sec = Math.round(s % 60)
    return `${m}m ${sec}s`
  }

  if (loading) return <div className="text-gray-400 text-center py-12">Loading history…</div>

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-white font-semibold text-lg">📊 Processing History</h2>
        {history.length > 0 && (
          <button
            onClick={clearHistory}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition"
          >
            Clear History
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500 text-sm">No processing runs recorded yet.</p>
          <p className="text-gray-600 text-xs mt-1">Run a processing job from the Overlays tab to see history here.</p>
        </div>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400 text-xs">
                <th className="px-4 py-3 text-left font-medium">Timestamp</th>
                <th className="px-4 py-3 text-left font-medium">Type</th>
                <th className="px-4 py-3 text-left font-medium">Library</th>
                <th className="px-4 py-3 text-right font-medium">Success</th>
                <th className="px-4 py-3 text-right font-medium">Failed</th>
                <th className="px-4 py-3 text-right font-medium">Skipped</th>
                <th className="px-4 py-3 text-right font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {history.map((run, i) => (
                <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-700/30 transition">
                  <td className="px-4 py-2.5 text-gray-300 text-xs whitespace-nowrap">
                    {new Date(run.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                      run.type === 'process'
                        ? (run.force ? 'bg-purple-700/50 text-purple-300' : 'bg-blue-700/50 text-blue-300')
                        : 'bg-amber-700/50 text-amber-300'
                    }`}>
                      {run.type === 'process' ? (run.force ? 'Force' : 'Normal') : 'Restore'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-white text-xs">{run.library}</td>
                  <td className="px-4 py-2.5 text-right text-green-400 text-xs">{run.success}</td>
                  <td className="px-4 py-2.5 text-right text-red-400 text-xs">{run.failed}</td>
                  <td className="px-4 py-2.5 text-right text-gray-400 text-xs">{run.skipped}</td>
                  <td className="px-4 py-2.5 text-right text-gray-300 text-xs whitespace-nowrap">
                    {fmtDuration(run.duration_seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
