import { useState, useEffect, useRef } from 'react'

const DEFAULT_BADGE_STYLE = {
  individual_badge_size: 12,  // Individual badge size (% of poster width)
  font_size_multiplier: 1.0,  // Multiplier for font sizes
  logo_size_multiplier: 1.0,  // Multiplier for logo within badge
  rating_color: '#FFD700',    // Gold color (default)
  background_opacity: 128,    // 0-255, default 128 (50%)
  font_family: 'DejaVu Sans Bold',  // Font family
  status_overlay: 'none', // none | auto | current | renewed | cancelled
  status_position: { x: 50, y: 50 }, // {x, y} percentage — draggable like badges
  status_rotation: 0 // 0 = horizontal, 90 = vertical (top-to-bottom), -90 = vertical (bottom-to-top)
}

function Dashboard({ onStartProcessing, onLibrarySelect }) {
  const [libraries, setLibraries] = useState([])
  const [selectedLibrary, setSelectedLibrary] = useState(null)   // for stats / preview
  const [selectedLibraries, setSelectedLibraries] = useState([]) // for processing (names)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [position, setPosition] = useState('northwest')  // Keep for backward compat display
  const [badgePositions, setBadgePositions] = useState(() => {
    // Load from localStorage or set smart defaults (4 corners)
    const saved = localStorage.getItem('kometizarr_badge_positions')
    return saved ? JSON.parse(saved) : {
      tmdb: { x: 2, y: 2 },           // Top-left
      imdb: { x: 70, y: 2 },          // Top-right (70% across to fit ~12% badge + margin)
      rt_critic: { x: 2, y: 78 },      // Bottom-left (78% down to fit ~20% badge + margin)
      rt_audience: { x: 70, y: 78 }    // Bottom-right
    }
  })
  const [activeDragBadge, setActiveDragBadge] = useState(null)  // Which badge is being dragged
  const [alignmentGuides, setAlignmentGuides] = useState([])  // Visual alignment guides
  const [force, setForce] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResults, setPreviewResults] = useState(null)  // null = closed, [] = loading/empty
  const [previewDebug, setPreviewDebug] = useState(null)
  const [ratingSources, setRatingSources] = useState(() => {
    // Load from localStorage or default to all enabled
    const saved = localStorage.getItem('kometizarr_rating_sources')
    return saved ? JSON.parse(saved) : {
      tmdb: true,
      imdb: true,
      rt_critic: true,
      rt_audience: true
    }
  })
  const [badgeStyle, setBadgeStyle] = useState(() => {
    // Load from localStorage or use defaults
    const saved = localStorage.getItem('kometizarr_badge_style')
    if (!saved) return DEFAULT_BADGE_STYLE

    try {
      return { ...DEFAULT_BADGE_STYLE, ...JSON.parse(saved) }
    } catch {
      return DEFAULT_BADGE_STYLE
    }
  })

  // Keep a ref so handleMouseUp can read latest badgePositions without stale closure
  const badgePositionsRef = useRef(badgePositions)
  useEffect(() => { badgePositionsRef.current = badgePositions }, [badgePositions])

  // Persist badge settings to server so webhook/cron use the same settings as the UI
  const persistBadgeSettings = async (patch) => {
    try {
      const res = await fetch('/api/settings')
      const current = await res.json()
      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, ...patch }),
      })
    } catch (e) {
      console.warn('Failed to persist badge settings to server:', e)
    }
  }

  useEffect(() => {
    fetchLibraries()
    // Sync localStorage badge settings to server on mount so webhook/cron work
    // without requiring the user to manually interact with the UI after upgrading
    fetch('/api/settings')
      .then(r => r.json())
      .then(s => {
        if (!s.badge_positions || !s.badge_style) {
          persistBadgeSettings({ badge_positions: badgePositions, badge_style: badgeStyle, rating_sources: ratingSources })
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (selectedLibrary) {
      fetchStats(selectedLibrary.name)
    }
  }, [selectedLibrary])

  const fetchLibraries = async () => {
    try {
      const res = await fetch('/api/libraries')
      const data = await res.json()
      if (data.libraries) {
        setLibraries(data.libraries)
        if (data.libraries.length > 0) {
          setSelectedLibrary(data.libraries[0])
          // Restore previously selected libraries from localStorage
          const saved = localStorage.getItem('kometizarr_selected_libraries')
          if (saved) {
            try {
              const parsed = JSON.parse(saved)
              const valid = parsed.filter(n => data.libraries.some(l => l.name === n))
              setSelectedLibraries(valid)
            } catch { setSelectedLibraries([]) }
          }
        }
      }
    } catch (error) {
      console.error('Failed to fetch libraries:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async (libraryName) => {
    try {
      const res = await fetch(`/api/library/${libraryName}/stats`)
      const data = await res.json()
      setStats(data)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }

  const toggleLibrarySelection = (lib) => {
    setSelectedLibrary(lib) // always update stats to last-clicked
    setSelectedLibraries(prev => {
      const next = prev.includes(lib.name) ? prev.filter(n => n !== lib.name) : [...prev, lib.name]
      localStorage.setItem('kometizarr_selected_libraries', JSON.stringify(next))
      return next
    })
    if (onLibrarySelect) onLibrarySelect(lib)
  }

  const toggleRatingSource = (source) => {
    const updated = { ...ratingSources, [source]: !ratingSources[source] }
    setRatingSources(updated)
    localStorage.setItem('kometizarr_rating_sources', JSON.stringify(updated))
    persistBadgeSettings({ rating_sources: updated })
  }

  const updateBadgeStyle = (key, value) => {
    const updated = { ...badgeStyle, [key]: value }
    setBadgeStyle(updated)
    localStorage.setItem('kometizarr_badge_style', JSON.stringify(updated))
    persistBadgeSettings({ badge_style: updated })
  }

  const handlePosterDrag = (e, badgeSource) => {
    if (!activeDragBadge && !badgeSource) return  // Not dragging

    const source = badgeSource || activeDragBadge
    if (!source) return

    // Status overlay drag — store position in badgeStyle
    if (source === 'status') {
      const rect = e.currentTarget.getBoundingClientRect()
      const clickX = e.clientX - rect.left
      const clickY = e.clientY - rect.top
      let xPercent = (clickX / rect.width) * 100
      let yPercent = (clickY / rect.height) * 100
      xPercent = Math.max(2, Math.min(xPercent, 98))
      yPercent = Math.max(2, Math.min(yPercent, 98))
      const newPos = { x: Math.round(xPercent), y: Math.round(yPercent) }
      const updated = { ...badgeStyle, status_position: newPos }
      setBadgeStyle(updated)
      localStorage.setItem('kometizarr_badge_style', JSON.stringify(updated))
      return
    }

    if (!ratingSources[source]) return  // Badge not enabled

    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const clickY = e.clientY - rect.top

    // Calculate position as percentage of poster dimensions (0-100)
    // Individual badges are small (~12% of poster width)
    const badgeWidthPercent = badgeStyle.individual_badge_size || 12
    const badgeHeightPercent = badgeWidthPercent * 1.4  // 1.4x aspect ratio

    // Center badge on cursor
    let xPercent = (clickX / rect.width) * 100 - (badgeWidthPercent / 2)
    let yPercent = (clickY / rect.height) * 100 - (badgeHeightPercent / 2)

    // Detect alignment with other badges (before clamping)
    const guides = []
    const threshold = 2  // Snap within 2%
    let alignedX = false
    let alignedY = false

    Object.keys(badgePositions).forEach(otherSource => {
      if (otherSource === source || !ratingSources[otherSource]) return

      const other = badgePositions[otherSource]
      const otherRight = other.x + badgeWidthPercent
      const otherBottom = other.y + badgeHeightPercent
      const otherCenterX = other.x + badgeWidthPercent / 2
      const otherCenterY = other.y + badgeHeightPercent / 2

      const dragRight = xPercent + badgeWidthPercent
      const dragBottom = yPercent + badgeHeightPercent
      const dragCenterX = xPercent + badgeWidthPercent / 2
      const dragCenterY = yPercent + badgeHeightPercent / 2

      // Check vertical alignments (X-axis) - only snap if not already aligned
      if (!alignedX) {
        if (Math.abs(xPercent - other.x) < threshold) {
          // Left edges align
          xPercent = other.x
          guides.push({ type: 'vertical', position: other.x })
          alignedX = true
        } else if (Math.abs(dragRight - otherRight) < threshold) {
          // Right edges align
          xPercent = otherRight - badgeWidthPercent
          guides.push({ type: 'vertical', position: otherRight })
          alignedX = true
        } else if (Math.abs(dragCenterX - otherCenterX) < threshold) {
          // Centers align
          xPercent = otherCenterX - badgeWidthPercent / 2
          guides.push({ type: 'vertical', position: otherCenterX })
          alignedX = true
        }
      }

      // Check horizontal alignments (Y-axis) - only snap if not already aligned
      if (!alignedY) {
        if (Math.abs(yPercent - other.y) < threshold) {
          // Top edges align
          yPercent = other.y
          guides.push({ type: 'horizontal', position: other.y })
          alignedY = true
        } else if (Math.abs(dragBottom - otherBottom) < threshold) {
          // Bottom edges align
          yPercent = otherBottom - badgeHeightPercent
          guides.push({ type: 'horizontal', position: otherBottom })
          alignedY = true
        } else if (Math.abs(dragCenterY - otherCenterY) < threshold) {
          // Centers align
          yPercent = otherCenterY - badgeHeightPercent / 2
          guides.push({ type: 'horizontal', position: otherCenterY })
          alignedY = true
        }
      }
    })

    // Clamp to edges AFTER alignment - simple 0-100% bounds (badges can overlap edges)
    xPercent = Math.max(0, Math.min(xPercent, 100))
    yPercent = Math.max(0, Math.min(yPercent, 100))

    setAlignmentGuides(guides)

    const newPosition = { x: Math.round(xPercent), y: Math.round(yPercent) }

    // Update only this badge's position
    const updated = { ...badgePositions, [source]: newPosition }
    setBadgePositions(updated)
    localStorage.setItem('kometizarr_badge_positions', JSON.stringify(updated))
  }

  const handleBadgeMouseDown = (e, badgeSource) => {
    e.stopPropagation()  // Prevent poster click
    setActiveDragBadge(badgeSource)
    // Don't move on initial click - only move when dragging (mousemove)
  }

  const handlePosterMouseMove = (e) => {
    if (activeDragBadge) {
      handlePosterDrag(e)
    }
  }

  const handleMouseUp = () => {
    if (activeDragBadge) {
      if (activeDragBadge === 'status') {
        // Persist status position from latest badgeStyle
        const latestStyle = JSON.parse(localStorage.getItem('kometizarr_badge_style') || '{}')
        persistBadgeSettings({ badge_style: latestStyle })
      } else {
        // Save final drag position to server (use ref to get latest state)
        persistBadgeSettings({ badge_positions: badgePositionsRef.current })
      }
    }
    setActiveDragBadge(null)
    setAlignmentGuides([])  // Clear alignment guides
  }

  const startProcessing = async () => {
    if (selectedLibraries.length === 0) return

    const enabledBadgePositions = {}
    Object.keys(ratingSources).forEach(source => {
      if (ratingSources[source] && badgePositions[source]) {
        enabledBadgePositions[source] = badgePositions[source]
      }
    })

    const commonOptions = {
      position,
      badge_positions: enabledBadgePositions,
      force,
      rating_sources: ratingSources,
      badge_style: badgeStyle,
    }

    try {
      const isBatch = selectedLibraries.length > 1
      const res = await fetch(isBatch ? '/api/process-batch' : '/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          isBatch
            ? { library_names: selectedLibraries, ...commonOptions }
            : { library_name: selectedLibraries[0], ...commonOptions }
        ),
      })

      const data = await res.json()
      if (data.status === 'started') {
        onStartProcessing()
      }
    } catch (error) {
      console.error('Failed to start processing:', error)
    }
  }

  const restoreOriginals = async () => {
    if (!selectedLibrary) return

    if (!confirm(`Restore all original posters in ${selectedLibrary.name}? This will remove all overlays.`)) {
      return
    }

    try {
      const res = await fetch('/api/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_name: selectedLibrary.name,
        }),
      })

      const data = await res.json()
      if (data.status === 'started') {
        onStartProcessing() // Use same callback to show progress view
      } else if (data.error) {
        alert(`Error: ${data.error}`)
      }
    } catch (error) {
      console.error('Failed to restore originals:', error)
      alert('Failed to restore originals')
    }
  }

  const previewPosters = async () => {
    if (!selectedLibrary) return
    setPreviewLoading(true)
    setPreviewResults([])
    setPreviewDebug(null)

    const enabledBadgePositions = {}
    Object.keys(ratingSources).forEach(source => {
      if (ratingSources[source] && badgePositions[source]) {
        enabledBadgePositions[source] = badgePositions[source]
      }
    })

    try {
      const res = await fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_name: selectedLibrary.name,
          badge_positions: enabledBadgePositions,
          rating_sources: ratingSources,
          badge_style: badgeStyle,
          count: 3,
        }),
      })
      const contentType = res.headers.get('content-type') || ''
      if (!res.ok) {
        throw new Error(`Preview request failed (${res.status})`)
      }
      if (!contentType.includes('application/json')) {
        throw new Error('Preview response was not JSON (likely proxy timeout page)')
      }

      const data = await res.json()
      setPreviewResults(data.previews || [])
      setPreviewDebug(data.debug || null)
    } catch (error) {
      console.error('Preview failed:', error)
      setPreviewResults([])
      setPreviewDebug({ error: error.message })
    } finally {
      setPreviewLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading libraries...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Library Selection */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Select Libraries</h2>
          {libraries.length > 1 && (
            <button
              onClick={() =>
                {
                  const next = selectedLibraries.length === libraries.length ? [] : libraries.map(l => l.name)
                  setSelectedLibraries(next)
                  localStorage.setItem('kometizarr_selected_libraries', JSON.stringify(next))
                }
              }
              className="text-xs text-gray-400 hover:text-gray-200 transition"
            >
              {selectedLibraries.length === libraries.length ? 'Deselect all' : 'Select all'}
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {libraries.map((lib) => {
            const isSelected = selectedLibraries.includes(lib.name)
            const isPrimary = selectedLibrary?.name === lib.name
            return (
              <button
                key={lib.name}
                onClick={() => toggleLibrarySelection(lib)}
                className={`p-4 rounded-lg border-2 transition relative text-left ${
                  isSelected
                    ? 'border-blue-500 bg-blue-900/20'
                    : 'border-gray-700 hover:border-gray-600'
                }`}
              >
                {/* Checkbox indicator */}
                <div className={`absolute top-3 right-3 w-5 h-5 rounded border-2 flex items-center justify-center text-xs font-bold transition ${
                  isSelected ? 'border-blue-500 bg-blue-500 text-white' : 'border-gray-500'
                }`}>
                  {isSelected && '✓'}
                </div>
                <div className="font-semibold pr-7">{lib.name}</div>
                <div className="text-sm text-gray-400 mt-1">
                  {lib.type === 'movie' ? '🎬' : '📺'} {lib.count} items
                </div>
                {isPrimary && isSelected && (
                  <div className="text-xs text-blue-400 mt-1">Stats shown below</div>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Library Stats */}
      {stats && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4">Library Statistics</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">Total Items</div>
              <div className="text-3xl font-bold mt-1">{stats.total_items}</div>
            </div>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">With Backups</div>
              <div className="text-3xl font-bold mt-1 text-green-400">
                {stats.processed_items}
              </div>
            </div>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">Backup Coverage</div>
              <div className="text-3xl font-bold mt-1 text-blue-400">
                {stats.success_rate}%
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Processing Options */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-4">Processing Options</h2>
        <div className="space-y-4">
          {/* Position & Styling - Side by Side Layout */}
          <div>
            <label className="block text-sm font-medium mb-2">Badge Positions & Styling</label>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="flex items-start gap-6">
                {/* LEFT: Draggable Poster Preview */}
                <div className="flex-shrink-0">
                  <svg
                    viewBox="0 0 120 168"
                    className="w-48 h-auto select-none"
                    onMouseMove={handlePosterMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                  >
                    {/* Poster Background */}
                    <rect x="0" y="0" width="120" height="168" fill="#1f2937" stroke="#4b5563" strokeWidth="2" rx="3" />

                    {/* Status Overlay Preview — draggable */}
                    {(() => {
                      const status = badgeStyle.status_overlay || 'none'
                      if (status === 'none') return null

                      const statusMap = {
                        auto: { label: 'AUTO', color: '#9ca3af' },
                        cancelled: { label: 'CANCELLED', color: '#dc2626' },
                        renewed: { label: 'RENEWED', color: '#22c55e' },
                        current: { label: 'CURRENT', color: '#3b82f6' }
                      }

                      const statusConfig = statusMap[status]
                      if (!statusConfig) return null

                      const sPos = badgeStyle.status_position || { x: 50, y: 50 }
                      const sx = typeof sPos === 'object' ? (sPos.x / 100) * 120 : 60
                      const sy = typeof sPos === 'object' ? (sPos.y / 100) * 168 : 84
                      const rot = badgeStyle.status_rotation || 0

                      const labelLen = statusConfig.label.length
                      const textW = Math.max(labelLen * 7.5 + 6, 40)
                      const textH = 16
                      // For vertical text, swap pill dimensions
                      const bgW = rot === 0 ? textW : textH
                      const bgH = rot === 0 ? textH : textW

                      return (
                        <g
                          className="cursor-move"
                          onMouseDown={(e) => handleBadgeMouseDown(e, 'status')}
                        >
                          <rect
                            x={sx - bgW / 2}
                            y={sy - bgH / 2}
                            width={bgW}
                            height={bgH}
                            fill="#000"
                            fillOpacity="0.7"
                            rx="3"
                          />
                          <text
                            x={sx}
                            y={sy}
                            fontSize="11"
                            fontWeight="700"
                            fill={statusConfig.color}
                            textAnchor="middle"
                            dominantBaseline="central"
                            transform={rot !== 0 ? `rotate(${rot} ${sx} ${sy})` : undefined}
                            className="pointer-events-none select-none"
                          >
                            {statusConfig.label}
                          </text>
                        </g>
                      )
                    })()}

                    {/* Individual Badges - dynamically sized and styled */}
                    {(() => {
                      // Calculate badge dimensions based on style settings
                      const badgeSizePercent = badgeStyle.individual_badge_size || 12
                      const badgeWidth = (badgeSizePercent / 100) * 120  // Scale to SVG viewBox
                      const badgeHeight = badgeWidth * 1.4  // 1.4 aspect ratio
                      const logoMultiplier = badgeStyle.logo_size_multiplier || 1.0
                      const fontMultiplier = badgeStyle.font_size_multiplier || 1.0
                      // Logo occupies top 60% of badge, scaled by logo_size_multiplier (max 2.0 → full area)
                      const logoAreaHeight = badgeHeight * 0.6 * Math.min(logoMultiplier / 2.0, 1.0)
                      // Font size applies to bottom 40% (rating number), scaled by font_size_multiplier
                      const fontSize = (badgeWidth / 14) * 8 * fontMultiplier
                      const opacity = (badgeStyle.background_opacity || 128) / 255

                      // Map font family to CSS font-family for SVG
                      const getFontFamily = (fontName) => {
                        if (fontName.includes('Mono')) return 'monospace'
                        if (fontName.includes('Serif')) return 'serif'
                        return 'sans-serif'
                      }

                      const getFontStyle = (fontName) => {
                        return fontName.includes('Oblique') || fontName.includes('Italic') ? 'italic' : 'normal'
                      }

                      const getFontWeight = (fontName) => {
                        return fontName.includes('Bold') ? 'bold' : 'normal'
                      }

                      const fontFamily = getFontFamily(badgeStyle.font_family || 'DejaVu Sans Bold')
                      const fontStyle = getFontStyle(badgeStyle.font_family || 'DejaVu Sans Bold')
                      const fontWeight = getFontWeight(badgeStyle.font_family || 'DejaVu Sans Bold')

                      return (
                        <>
                          {ratingSources.tmdb && badgePositions.tmdb && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'tmdb')}
                            >
                              <rect x={(badgePositions.tmdb.x / 100) * 120} y={(badgePositions.tmdb.y / 100) * 168} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.tmdb.x / 100) * 120 + badgeWidth * 0.1} y={(badgePositions.tmdb.y / 100) * 168 + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#4a9eff" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.tmdb.x / 100) * 120 + badgeWidth / 2} y={(badgePositions.tmdb.y / 100) * 168 + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">T</text>
                            </g>
                          )}

                          {ratingSources.imdb && badgePositions.imdb && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'imdb')}
                            >
                              <rect x={(badgePositions.imdb.x / 100) * 120} y={(badgePositions.imdb.y / 100) * 168} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.imdb.x / 100) * 120 + badgeWidth * 0.1} y={(badgePositions.imdb.y / 100) * 168 + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#f5c518" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.imdb.x / 100) * 120 + badgeWidth / 2} y={(badgePositions.imdb.y / 100) * 168 + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">I</text>
                            </g>
                          )}

                          {ratingSources.rt_critic && badgePositions.rt_critic && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_critic')}
                            >
                              <rect x={(badgePositions.rt_critic.x / 100) * 120} y={(badgePositions.rt_critic.y / 100) * 168} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.rt_critic.x / 100) * 120 + badgeWidth * 0.1} y={(badgePositions.rt_critic.y / 100) * 168 + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.rt_critic.x / 100) * 120 + badgeWidth / 2} y={(badgePositions.rt_critic.y / 100) * 168 + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">C</text>
                            </g>
                          )}

                          {ratingSources.rt_audience && badgePositions.rt_audience && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_audience')}
                            >
                              <rect x={(badgePositions.rt_audience.x / 100) * 120} y={(badgePositions.rt_audience.y / 100) * 168} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.rt_audience.x / 100) * 120 + badgeWidth * 0.1} y={(badgePositions.rt_audience.y / 100) * 168 + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.25} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.rt_audience.x / 100) * 120 + badgeWidth / 2} y={(badgePositions.rt_audience.y / 100) * 168 + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">A</text>
                            </g>
                          )}
                        </>
                      )
                    })()}

                    {/* Alignment Guides */}
                    {alignmentGuides.map((guide, index) => {
                      if (guide.type === 'vertical') {
                        // Vertical line (for X-axis alignment)
                        const x = (guide.position / 100) * 120
                        return (
                          <line
                            key={`guide-${index}`}
                            x1={x}
                            y1={0}
                            x2={x}
                            y2={168}
                            stroke="#3b82f6"
                            strokeWidth="1"
                            strokeDasharray="4,4"
                            className="pointer-events-none"
                          />
                        )
                      } else {
                        // Horizontal line (for Y-axis alignment)
                        const y = (guide.position / 100) * 168
                        return (
                          <line
                            key={`guide-${index}`}
                            x1={0}
                            y1={y}
                            x2={120}
                            y2={y}
                            stroke="#3b82f6"
                            strokeWidth="1"
                            strokeDasharray="4,4"
                            className="pointer-events-none"
                          />
                        )
                      }
                    })}
                  </svg>
                  <div className="text-xs text-gray-500 mt-2 space-y-1">
                    <p className="font-medium">💡 Drag badges to position</p>
                    <div className="text-gray-400 leading-relaxed">
                      <span className="font-bold text-white">T</span>=<span className="font-bold">TMDB</span> • <span className="font-bold text-white">I</span>=<span className="font-bold">IMDb</span> • <span className="font-bold text-white">C</span>=<span className="font-bold">RT Critic</span> • <span className="font-bold text-white">A</span>=<span className="font-bold">RT Audience</span>
                      {(badgeStyle.status_overlay || 'none') !== 'none' && (
                        <span className="block mt-0.5">Status label is also draggable</span>
                      )}
                    </div>
                    {/* Live position readout */}
                    {(badgeStyle.status_overlay || 'none') !== 'none' && (() => {
                      const sPos = badgeStyle.status_position || { x: 50, y: 50 }
                      const rot = badgeStyle.status_rotation || 0
                      const rotLabel = rot === 0 ? 'Horizontal' : rot === 90 ? 'Vertical ↓' : 'Vertical ↑'
                      return (
                        <div className="mt-1 px-2 py-1 bg-gray-800 rounded border border-gray-700 text-gray-300 font-mono text-[10px]">
                          Status: x={sPos.x}% y={sPos.y}% • {rotLabel}
                        </div>
                      )
                    })()}
                  </div>
                </div>

                {/* RIGHT: Styling Controls */}
                <div className="flex-1 space-y-3">
                  {/* Badge Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Badge Size: {Math.round(((badgeStyle.individual_badge_size - 8) / (30 - 8)) * 100)}%
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={Math.round(((badgeStyle.individual_badge_size - 8) / (30 - 8)) * 100)}
                      onChange={(e) => {
                        // Map 0-100 slider to 8-30% actual badge size
                        const sliderValue = parseInt(e.target.value)
                        const actualSize = 8 + (sliderValue / 100) * (30 - 8)
                        updateBadgeStyle('individual_badge_size', Math.round(actualSize))
                      }}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Font Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Font Size: {badgeStyle.font_size_multiplier.toFixed(1)}x
                    </label>
                    <input
                      type="range"
                      min="0.5"
                      max="2.0"
                      step="0.1"
                      value={badgeStyle.font_size_multiplier}
                      onChange={(e) => updateBadgeStyle('font_size_multiplier', parseFloat(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Logo Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Logo Size: {(badgeStyle.logo_size_multiplier || 1.0).toFixed(1)}x
                    </label>
                    <input
                      type="range"
                      min="0.3"
                      max="2.0"
                      step="0.1"
                      value={badgeStyle.logo_size_multiplier || 1.0}
                      onChange={(e) => updateBadgeStyle('logo_size_multiplier', parseFloat(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Font and Color - Side by Side */}
                  <div className="grid grid-cols-2 gap-3">
                    {/* Font Family */}
                    <div>
                      <label className="text-xs text-gray-400 block mb-1">
                        Font
                      </label>
                      <select
                        value={badgeStyle.font_family}
                        onChange={(e) => updateBadgeStyle('font_family', e.target.value)}
                        className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                      >
                        <option value="DejaVu Sans Bold">Sans Bold (Default)</option>
                        <option value="DejaVu Sans">Sans Regular</option>
                        <option value="DejaVu Sans Bold Oblique">Sans Bold Italic</option>
                        <option value="DejaVu Sans Oblique">Sans Italic</option>
                        <option value="DejaVu Serif Bold">Serif Bold</option>
                        <option value="DejaVu Serif">Serif Regular</option>
                        <option value="DejaVu Serif Bold Italic">Serif Bold Italic</option>
                        <option value="DejaVu Serif Italic">Serif Italic</option>
                        <option value="DejaVu Sans Mono Bold">Mono Bold</option>
                        <option value="DejaVu Sans Mono">Mono Regular</option>
                        <option value="DejaVu Sans Mono Oblique">Mono Italic</option>
                      </select>
                    </div>

                    {/* Rating Color */}
                    <div>
                      <label className="text-xs text-gray-400 block mb-1">
                        Color
                      </label>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={badgeStyle.rating_color}
                          onChange={(e) => updateBadgeStyle('rating_color', e.target.value)}
                          className="w-10 h-8 rounded border border-gray-700 bg-gray-800 cursor-pointer"
                        />
                        <span className="text-xs text-gray-400 font-mono text-xs">{badgeStyle.rating_color}</span>
                      </div>
                    </div>
                  </div>

                  {/* Background Opacity */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Background: {Math.round((badgeStyle.background_opacity / 255) * 100)}%
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="255"
                      step="5"
                      value={badgeStyle.background_opacity}
                      onChange={(e) => updateBadgeStyle('background_opacity', parseInt(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Series Status Overlay */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Status Overlay
                    </label>
                    <select
                      value={badgeStyle.status_overlay || 'none'}
                      onChange={(e) => updateBadgeStyle('status_overlay', e.target.value)}
                      className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                    >
                      <option value="none">Off</option>
                      <option value="auto">Auto (per item)</option>
                      <option value="current">Current</option>
                      <option value="renewed">Renewed</option>
                      <option value="cancelled">Cancelled</option>
                    </select>
                    <div className="mt-2 p-2 bg-gray-800/60 border border-gray-700 rounded text-xs text-gray-400 leading-relaxed">
                      <span className="text-gray-300 font-medium">Auto mode:</span> TV libraries only. Uses Plex status first, then TMDB fallback.
                      <span className="block mt-1">Mapped values: cancelled/ended → <span className="text-red-400">Cancelled</span>, renewed/returning → <span className="text-green-400">Renewed</span>, in production/continuing/current/running/planned/pilot → <span className="text-blue-400">Current</span>. Unknown status = no stamp.</span>
                    </div>
                  </div>

                  {/* Text Direction (rotation) — only show when status overlay is active */}
                  {badgeStyle.status_overlay && badgeStyle.status_overlay !== 'none' && (
                    <div>
                      <label className="text-xs text-gray-400 block mb-1">
                        Text Direction
                      </label>
                      <select
                        value={badgeStyle.status_rotation || 0}
                        onChange={(e) => updateBadgeStyle('status_rotation', Number(e.target.value))}
                        className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                      >
                        <option value={0}>Horizontal</option>
                        <option value={90}>Vertical ↓</option>
                        <option value={-90}>Vertical ↑</option>
                      </select>
                    </div>
                  )}

                  {/* Reset Button */}
                  <button
                    onClick={() => {
                      const defaults = DEFAULT_BADGE_STYLE
                      setBadgeStyle(defaults)
                      localStorage.setItem('kometizarr_badge_style', JSON.stringify(defaults))
                      persistBadgeSettings({ badge_style: defaults })
                    }}
                    className="w-full text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition"
                  >
                    ↺ Reset Styling
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Force */}
          <div className="flex items-center">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              className="mr-3"
              id="force-checkbox"
            />
            <label htmlFor="force-checkbox" className="text-sm">
              Force reprocess (use when updating ratings or changing which sources to display)
            </label>
          </div>
          {force && (
            <div className="mt-2 p-3 bg-blue-900/20 border border-blue-700/50 rounded text-sm text-blue-300">
              ℹ️ Uses original posters from backup to apply fresh overlays with updated ratings. Original backups are never overwritten.
            </div>
          )}

          {/* Rating Sources */}
          <div>
            <label className="block text-sm font-medium mb-2">Rating Sources to Display</label>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.tmdb}
                  onChange={() => toggleRatingSource('tmdb')}
                  className="mr-2"
                  id="tmdb-checkbox"
                />
                <label htmlFor="tmdb-checkbox" className="text-sm">
                  🎬 TMDB (0-10 scale)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.imdb}
                  onChange={() => toggleRatingSource('imdb')}
                  className="mr-2"
                  id="imdb-checkbox"
                />
                <label htmlFor="imdb-checkbox" className="text-sm">
                  ⭐ IMDb (0-10 scale)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.rt_critic}
                  onChange={() => toggleRatingSource('rt_critic')}
                  className="mr-2"
                  id="rt-critic-checkbox"
                />
                <label htmlFor="rt-critic-checkbox" className="text-sm">
                  🍅 RT Critic (0-100%)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.rt_audience}
                  onChange={() => toggleRatingSource('rt_audience')}
                  className="mr-2"
                  id="rt-audience-checkbox"
                />
                <label htmlFor="rt-audience-checkbox" className="text-sm">
                  🍿 RT Audience (0-100%)
                </label>
              </div>
            </div>
            {!Object.values(ratingSources).some(v => v) && (
              <div className="mt-2 p-3 bg-red-900/20 border border-red-700/50 rounded text-sm text-red-300">
                ⚠️ At least one rating source must be selected
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="grid grid-cols-3 gap-3">
            <button
              onClick={restoreOriginals}
              disabled={!selectedLibrary}
              className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              🔄 Restore
            </button>
            <button
              onClick={previewPosters}
              disabled={!selectedLibrary || previewLoading}
              className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              {previewLoading ? '⏳ Generating…' : '🔍 Preview'}
            </button>
            <button
              onClick={startProcessing}
              disabled={selectedLibraries.length === 0}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              {selectedLibraries.length > 1 ? `▶️ Process (${selectedLibraries.length})` : '▶️ Process'}
            </button>
          </div>
        </div>
      </div>
      <PreviewModal
        results={previewResults}
        debug={previewDebug}
        loading={previewLoading}
        onClose={() => setPreviewResults(null)}
      />
    </div>
  )
}

// Preview Modal — rendered outside the main panel so it overlays everything
function PreviewModal({ results, debug, loading, onClose }) {
  if (results === null) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={onClose}>
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-6 max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-white">🔍 Preview — 3 random items</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">✕</button>
        </div>

        {loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12">Fetching ratings & rendering posters…</div>
        )}

        {!loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12 space-y-2">
            <div>No results — library may have no rated items with matching sources.</div>
            {debug && (
              <div className="text-xs text-gray-500">
                {debug.error
                  ? `error=${debug.error}`
                  : `sampled=${debug.sampled}/${debug.total_items} · no_ids=${debug.skipped_no_ids} · no_ratings=${debug.skipped_no_ratings} · no_poster=${debug.skipped_no_poster} · download_failed=${debug.skipped_download_failed} · render_failed=${debug.skipped_render_failed}`}
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-3 gap-5">
          {results.map((item, i) => (
            <div key={i} className="flex flex-col items-center gap-2">
              <img
                src={`data:image/jpeg;base64,${item.image}`}
                alt={item.title}
                className="rounded-lg w-full object-cover shadow-lg"
              />
              <div className="text-center">
                <div className="text-sm font-medium text-white truncate w-full">{item.title} {item.year && <span className="text-gray-400">({item.year})</span>}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {Object.entries(item.ratings).map(([k, v]) => `${k.toUpperCase()}: ${v}`).join(' · ')}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  Status Overlay: {(item.status_overlay || 'none').toUpperCase()}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default Dashboard
