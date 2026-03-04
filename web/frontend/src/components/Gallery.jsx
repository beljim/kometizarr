import { useState, useEffect } from 'react'

const STATUS_COLORS = {
  overlay_applied: { bg: 'bg-green-700/50', text: 'text-green-300', label: 'Overlay' },
  backup_only: { bg: 'bg-blue-700/50', text: 'text-blue-300', label: 'Backup Only' },
  excluded: { bg: 'bg-red-700/50', text: 'text-red-300', label: 'Excluded' },
  unknown: { bg: 'bg-gray-700/50', text: 'text-gray-300', label: 'Unknown' },
}

const STATUS_OVERRIDE_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'current', label: 'Current' },
  { value: 'renewed', label: 'Renewed' },
  { value: 'ended', label: 'Ended' },
  { value: 'cancelled', label: 'Cancelled' },
]

// Match backend sanitization: keep only alphanumeric, spaces, hyphens, underscores
const safeTitle = (t) => t.replace(/[^a-zA-Z0-9 \-_]/g, '').trim()

export default function Gallery() {
  const [libraries, setLibraries] = useState([])
  const [selectedLib, setSelectedLib] = useState('')
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [posterVersion, setPosterVersion] = useState('overlay') // 'overlay' or 'original'
  const [statusOverrides, setStatusOverrides] = useState({}) // { title: status }

  useEffect(() => {
    fetch('/api/libraries').then(r => r.json()).then(d => setLibraries(d.libraries || []))
  }, [])

  const fetchGallery = async (lib, pg = 1) => {
    if (!lib) return
    setLoading(true)
    try {
      const res = await fetch(`/api/gallery/${encodeURIComponent(lib)}?page=${pg}`)
      const data = await res.json()
      setItems(data.items || [])
      setTotalPages(data.pages || 1)
      setTotal(data.total || 0)
      setPage(pg)
    } catch (e) {
      console.error('Gallery fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedLib) fetchGallery(selectedLib, 1)
    // Fetch status overrides for TV libraries
    const lib = libraries.find(l => l.name === selectedLib)
    if (lib && lib.type === 'show') {
      fetch(`/api/status-overrides/${encodeURIComponent(selectedLib)}`)
        .then(r => r.json())
        .then(d => setStatusOverrides(d.overrides || {}))
        .catch(() => setStatusOverrides({}))
    } else {
      setStatusOverrides({})
    }
  }, [selectedLib])

  const setStatusOverride = async (title, status) => {
    await fetch(`/api/status-overrides/${encodeURIComponent(selectedLib)}/${encodeURIComponent(title)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    })
    const key = safeTitle(title)
    if (status === 'auto') {
      const updated = { ...statusOverrides }
      delete updated[key]
      setStatusOverrides(updated)
    } else {
      setStatusOverrides(prev => ({ ...prev, [key]: status }))
    }
  }

  const toggleExclude = async (item) => {
    const method = item.status === 'excluded' ? 'DELETE' : 'POST'
    await fetch(`/api/gallery/${encodeURIComponent(selectedLib)}/${encodeURIComponent(item.title)}/exclude`, { method })
    fetchGallery(selectedLib, page)
  }

  const retryItem = async (item) => {
    await fetch(`/api/gallery/${encodeURIComponent(selectedLib)}/${encodeURIComponent(item.title)}/retry`, { method: 'POST' })
  }

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-white font-semibold text-lg">🖼️ Item Gallery</h2>
        <div className="flex items-center gap-3">
          <select
            value={selectedLib}
            onChange={e => setSelectedLib(e.target.value)}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
          >
            <option value="">Select library…</option>
            {libraries.map(lib => <option key={lib.name} value={lib.name}>{lib.name}</option>)}
          </select>
          {selectedLib && (
            <div className="flex bg-gray-800 border border-gray-700 rounded overflow-hidden">
              <button
                onClick={() => setPosterVersion('overlay')}
                className={`px-3 py-1.5 text-xs transition ${posterVersion === 'overlay' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
              >
                Overlay
              </button>
              <button
                onClick={() => setPosterVersion('original')}
                className={`px-3 py-1.5 text-xs transition ${posterVersion === 'original' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
              >
                Original
              </button>
            </div>
          )}
        </div>
      </div>

      {!selectedLib ? (
        <div className="text-center py-16">
          <p className="text-gray-500 text-sm">Select a library to browse processed items.</p>
        </div>
      ) : loading ? (
        <div className="text-gray-400 text-center py-12">Loading…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500 text-sm">No processed items found for this library.</p>
          <p className="text-gray-600 text-xs mt-1">Items appear here after their first processing run.</p>
        </div>
      ) : (
        <>
          <p className="text-xs text-gray-500">{total} items total</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {items.map(item => {
              const s = STATUS_COLORS[item.status] || STATUS_COLORS.unknown
              const currentLib = libraries.find(l => l.name === selectedLib)
              const isTv = currentLib?.type === 'show'
              return (
                <div key={item.title} className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden group">
                  {/* Poster thumbnail */}
                  <div className="relative aspect-[2/3] bg-gray-900">
                    <img
                      src={`/api/gallery/${encodeURIComponent(selectedLib)}/${encodeURIComponent(item.title)}/poster?version=${posterVersion}`}
                      alt={item.title}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={e => { e.target.style.display = 'none' }}
                    />
                    {/* Status badge */}
                    <span className={`absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${s.bg} ${s.text}`}>
                      {s.label}
                    </span>
                    {/* Hover actions */}
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition flex flex-col justify-end p-2 gap-1.5">
                      {isTv && (
                        <select
                          value={statusOverrides[safeTitle(item.title)] || 'auto'}
                          onChange={(e) => setStatusOverride(item.title, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-full px-2 py-1 bg-gray-800 border border-gray-600 rounded text-[10px] text-white"
                        >
                          {STATUS_OVERRIDE_OPTIONS.map(o => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      )}
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => toggleExclude(item)}
                          className={`flex-1 px-2 py-1 rounded text-[10px] font-medium transition ${
                            item.status === 'excluded'
                              ? 'bg-green-700 hover:bg-green-600 text-green-100'
                              : 'bg-red-700 hover:bg-red-600 text-red-100'
                          }`}
                        >
                          {item.status === 'excluded' ? 'Include' : 'Exclude'}
                        </button>
                        <button
                          onClick={() => retryItem(item)}
                          className="flex-1 px-2 py-1 bg-blue-700 hover:bg-blue-600 rounded text-[10px] font-medium text-blue-100 transition"
                        >
                          Retry
                        </button>
                      </div>
                    </div>
                  </div>
                  {/* Title + ratings */}
                  <div className="p-2">
                    <p className="text-white text-xs font-medium truncate" title={item.title}>
                      {item.title}
                    </p>
                    {item.year && <p className="text-gray-500 text-[10px]">{item.year}</p>}
                    {item.ratings && Object.keys(item.ratings).length > 0 && (
                      <div className="flex gap-2 mt-1 text-[10px] text-gray-400">
                        {Object.entries(item.ratings).map(([src, val]) => (
                          <span key={src}>{src.toUpperCase()}: {val}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button
                onClick={() => fetchGallery(selectedLib, page - 1)}
                disabled={page <= 1}
                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 rounded text-sm text-white transition"
              >
                ← Prev
              </button>
              <span className="text-gray-400 text-sm">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => fetchGallery(selectedLib, page + 1)}
                disabled={page >= totalPages}
                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 rounded text-sm text-white transition"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
