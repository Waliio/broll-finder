import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CAT_COLORS, SAMPLE_SCRIPT, call, type Clip } from './api'

type Tab = 'mission' | 'live' | 'results' | 'images' | 'brain' | 'settings' | 'history'
type Moment = { id: number; topic: string; status: string; clips: number }

const STAGES = ['Transcribe', 'Plan', 'Search', 'Transcripts', 'Score', 'Export']

export default function App() {
  const [tab, setTab] = useState<Tab>('mission')
  const [script, setScript] = useState('')
  const [brain, setBrain] = useState('offline')
  const [moments, setMoments] = useState(15)
  const [videosPer, setVideosPer] = useState(4)
  const [minScore, setMinScore] = useState(6)
  const [findImages, setFindImages] = useState(true)
  const [autoDownload, setAutoDownload] = useState(false)
  const [status, setStatus] = useState('Idle')
  const [logs, setLogs] = useState<string[]>([])
  const [momentList, setMomentList] = useState<Moment[]>([])
  const [clips, setClips] = useState<Clip[]>([])
  const [images, setImages] = useState<Record<string, unknown>[]>([])
  const [outDir, setOutDir] = useState('')
  const [toast, setToast] = useState('')
  const [brainText, setBrainText] = useState('')
  const [brainMsg, setBrainMsg] = useState('')
  const [brainTest, setBrainTest] = useState<Record<string, unknown> | null>(null)
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [history, setHistory] = useState<Record<string, unknown>[]>([])
  const [selectedMoment, setSelectedMoment] = useState<number | null>(null)
  const [catFilter, setCatFilter] = useState('All')
  const [scoreFilter, setScoreFilter] = useState(0)
  const [searchBox, setSearchBox] = useState('')
  const [selectedImage, setSelectedImage] = useState<Record<string, unknown> | null>(null)
  const [showLog, setShowLog] = useState(true)
  const [filePath, setFilePath] = useState('')
  const polling = useRef<number | null>(null)

  const loadSettings = useCallback(async () => {
    const s = await call<Record<string, unknown>>('get_settings')
    if (s) { setSettings(s); setBrain(String(s.ai_provider || 'offline')); setMoments(Number(s.max_moments || 15)); setVideosPer(Number(s.videos_per_moment || 4)); setMinScore(Number(s.min_score || 6)); setFindImages(Boolean(s.also_find_images)); }
  }, [])

  const loadBrain = useCallback(async (mode: string) => {
    const b = await call<{ text: string }>('get_brain', mode)
    if (b) setBrainText(b.text)
  }, [])

  useEffect(() => { loadSettings(); loadBrain('offline') }, [loadSettings, loadBrain])

  // Poll Python for scan events (progress, moments, clips, logs).
  useEffect(() => {
    polling.current = window.setInterval(async () => {
      const r = await call<{ events: { type: string; [k: string]: unknown }[]; status: string }>('poll_events')
      if (!r) return
      setStatus(r.status)
      for (const e of r.events) {
        if (e.type === 'log') setLogs((l) => [...l.slice(-400), String(e.text)])
        if (e.type === 'moment') setMomentList((ms) => {
          const rest = ms.filter((m) => m.id !== Number(e.id))
          return [...rest, { id: Number(e.id), topic: String(e.topic || ''), status: String(e.status), clips: Number(e.clips || 0) }].sort((a, b) => a.id - b.id)
        })
        if (e.type === 'clip') setClips((c) => [...c, e.clip as Clip])
        if (e.type === 'image') setImages((im) => [...im, e.image as Record<string, unknown>])
        if (e.type === 'local_transcription') { setStatus('Local transcription'); setToast(String(e.text)) }
        if (e.type === 'search_blocked') setToast('YouTube is limiting requests. Wait 30-60 minutes or switch networks. Results so far are saved; press Resume later.')
        if (e.type === 'done') { setOutDir(String(e.out_dir)); setToast(`Done! ${e.clips} clips found.`); setTab('results') }
        if (e.type === 'error') setToast(String(e.text))
      }
    }, 900)
    return () => { if (polling.current) window.clearInterval(polling.current) }
  }, [])

  // Command palette: Ctrl+K jumps to Mission.
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setTab('mission') } }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  async function launch() {
    const opts = { ai_provider: brain, max_moments: moments, videos_per_moment: videosPer, min_score: minScore, also_find_images: findImages, auto_download_clips: autoDownload }
    setClips([]); setImages([]); setMomentList([]); setLogs([]); setTab('live')
    if (filePath) {
      const r = await call<{ ok: boolean; error?: string }>('start_scan_from_file', filePath, opts)
      if (r && !r.ok) { setToast(r.error || 'Could not start.'); setTab('mission') }
      return
    }
    if (!script.trim()) { setToast('Paste your script text first, or try the sample script.'); setTab('mission'); return }
    const r = await call<{ ok: boolean; error?: string }>('start_scan', script, opts)
    if (r && !r.ok) { setToast(r.error || 'Could not start.'); setTab('mission') }
  }

  async function loadHistory() {
    const r = await call<{ runs: Record<string, unknown>[] }>('list_history')
    if (r) setHistory(r.runs)
    setTab('history')
  }

  async function openRun(dir: string) {
    const r = await call<{ ok: boolean; data?: { clips: Clip[]; images: Record<string, unknown>[] } }>('get_run', dir)
    if (r?.ok && r.data) { setClips(r.data.clips || []); setImages(r.data.images || []); setOutDir(dir); setTab('results') }
  }

  const visibleClips = useMemo(() => clips.filter((c) =>
    !c.rejected && (catFilter === 'All' || c.category === catFilter) && c.score >= scoreFilter &&
    (searchBox === '' || (c.video_title + c.what_happens + c.key_quote).toLowerCase().includes(searchBox.toLowerCase())) &&
    (selectedMoment === null || c.topic_id === selectedMoment)), [clips, catFilter, scoreFilter, searchBox, selectedMoment])

  const momentOptions = useMemo(() => {
    const ids = [...new Set(clips.map((c) => c.topic_id))].sort((a, b) => a - b)
    return ids.map((id) => ({ id, line: clips.find((c) => c.topic_id === id)?.script_line || '', count: clips.filter((c) => c.topic_id === id).length }))
  }, [clips])

  const stageIndex = status === 'Idle' ? 0 : status === 'Local transcription' ? 3 : status === 'Scanning' ? 2 : 0

  return (
    <div className="min-h-screen" style={{ background: 'radial-gradient(900px 400px at 20% 0%, rgba(6,182,212,0.12), transparent), #0b0f14' }}>
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/10">
        <div><div className="text-xl font-black tracking-wide">B-ROLL FINDER <span className="text-cyan-400">◆ COMMAND CENTER</span></div>
        <div className="text-xs text-white/50">Paste a script. Get the exact YouTube moments. No API key needed.</div></div>
        <div className="flex items-center gap-3">
          <span className="chip" style={{ background: status === 'Idle' ? '#1f2937' : '#f59e0b', color: status === 'Idle' ? '#fff' : '#111' }}>{status}</span>
          <span className="text-xs text-white/50">Ctrl+K = Mission</span>
        </div>
      </header>

      <nav className="flex gap-2 px-5 py-3 flex-wrap">
        {(['mission', 'live', 'results', 'images', 'brain', 'settings', 'history'] as Tab[]).map((t) => (
          <button key={t} className={`chip ${tab === t ? 'active' : ''}`} onClick={() => { setTab(t); if (t === 'history') loadHistory() }}>{t.toUpperCase()}</button>
        ))}
      </nav>

      {toast && <div className="mx-5 mb-3 panel p-3 text-sm" style={{ borderColor: '#f59e0b' }}>{toast} <button className="float-right" onClick={() => setToast('')}>✕</button></div>}

      <main className="px-5 pb-8 max-w-7xl mx-auto">
        {tab === 'mission' && (
          <div className="grid md:grid-cols-5 gap-4">
            <div className="panel p-4 md:col-span-3">
              <h2 className="font-bold text-lg mb-2">1. Your script</h2>
              <div className="border-2 border-dashed border-cyan-500/40 rounded-xl p-6 text-center mb-3">
                <p className="mb-2">Choose an audio, video, .txt or .docx file, or paste the text below.</p>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean; path?: string; error?: string }>('choose_file'); if (r?.ok && r.path) { setFilePath(r.path); setToast(`File chosen: ${r.path}`) } else if (r) setToast(r.error || 'No file chosen.') }}>Choose file…</button>
                {filePath && <p className="text-xs mt-2 break-words">{filePath} <button className="underline" onClick={() => setFilePath('')}>Remove</button></p>}
                <p className="text-xs text-white/50 mt-2">Tip: the file is transcribed on your own PC. No upload, no key.</p>
              </div>
              <textarea className="textarea mono" rows={10} value={script} onChange={(e) => setScript(e.target.value)} placeholder="Paste your script text here..." />
              <button className="btn-ghost mt-3" onClick={() => setScript(SAMPLE_SCRIPT)}>Try with a sample script</button>
              <div className="text-xs text-white/50 mt-2">{script.split(/\s+/).filter(Boolean).length} words</div>
            </div>
            <div className="panel p-4 md:col-span-2">
              <h2 className="font-bold text-lg mb-3">2. Options</h2>
              <p className="text-sm text-white/60 mb-2">Brain (how it thinks)</p>
              <div className="flex gap-2 mb-4 flex-wrap">
                {(['offline', 'gemini', 'claude'] as const).map((b) => (
                  <button key={b} className={`chip ${brain === b ? 'active' : ''}`} onClick={() => { setBrain(b); loadBrain(b) }}>{b === 'offline' ? 'Offline (no key)' : b === 'gemini' ? 'Gemini (free key)' : 'Claude (paid key)'}</button>
                ))}
              </div>
              <label className="text-sm">Moments: {moments}</label>
              <input type="range" min={1} max={15} value={moments} onChange={(e) => setMoments(Number(e.target.value))} className="w-full" />
              <label className="text-sm">Videos per moment: {videosPer}</label>
              <input type="range" min={1} max={8} value={videosPer} onChange={(e) => setVideosPer(Number(e.target.value))} className="w-full" />
              <label className="text-sm">Minimum score: {minScore}</label>
              <input type="range" min={1} max={10} step={0.5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="w-full" />
              <label className="flex gap-2 items-center mt-3 text-sm"><input type="checkbox" checked={findImages} onChange={(e) => setFindImages(e.target.checked)} /> Also find images</label>
              <label className="flex gap-2 items-center mt-2 text-sm"><input type="checkbox" checked={autoDownload} onChange={(e) => setAutoDownload(e.target.checked)} /> Auto-download clips</label>
              <button className="btn w-full mt-5 text-lg" onClick={launch}>▶ LAUNCH SCAN</button>
              <p className="text-xs text-white/50 mt-2">Offline Brain works with no key at all. Gemini / Claude are optional upgrades in Settings.</p>
            </div>
          </div>
        )}

        {tab === 'live' && (
          <div>
            <div className="panel p-4 mb-4">
              <div className="flex flex-wrap gap-2">
                {STAGES.map((s, i) => (
                  <span key={s} className="chip" style={{ background: i === stageIndex ? '#f59e0b' : i < stageIndex ? '#06b6d4' : 'transparent', color: i <= stageIndex ? '#111' : '#fff' }}>{s}</span>
                ))}
              </div>
              <div className="flex gap-2 mt-4">
                <button className="btn-ghost" onClick={async () => { await call('stop_scan'); setStatus('Idle') }}>■ Stop</button>
                <button className="btn-ghost" onClick={async () => { if (outDir) await call('resume_scan', outDir) }}>↻ Resume</button>
                <span className="text-sm text-white/60 self-center">YouTube requests: safe mode, max {Number(settings.max_youtube_requests || 40)} per run. Images do not count.</span>
              </div>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="panel p-4">
                <h3 className="font-bold mb-3">Moment timeline</h3>
                {momentList.length === 0 && <p className="text-white/50 text-sm">Moments will appear here as the scan runs. Press Launch Scan on Mission first.</p>}
                {momentList.map((m) => (
                  <div key={m.id} className="flex justify-between border-b border-white/10 py-2 text-sm"><span>{m.id}. {m.topic || 'Moment'}</span><span className="mono">{m.status} · {m.clips} clips</span></div>
                ))}
              </div>
              <div className="panel p-4">
                <h3 className="font-bold mb-3">Live clip feed ({clips.length})</h3>
                {clips.slice(-8).reverse().map((c, i) => (
                  <div key={i} className="border-b border-white/10 py-2 text-sm"><span className="chip" style={{ borderColor: CAT_COLORS[c.category] || '#999', color: CAT_COLORS[c.category] || '#fff' }}>{c.category}</span> <b className="mono">{c.start_str}-{c.end_str}</b> · {c.video_title} · score {c.score}</div>
                ))}
                {clips.length === 0 && <p className="text-white/50 text-sm">Clips slide in here as they are found.</p>}
              </div>
            </div>
            <div className="panel p-4 mt-4">
              <button className="btn-ghost" onClick={() => setShowLog(!showLog)}>{showLog ? 'Hide log' : 'Show log'}</button>
              <button className="btn-ghost ml-2" onClick={() => navigator.clipboard.writeText(logs.join('\n'))}>Copy log</button>
              {showLog && <pre className="mono text-xs mt-3 whitespace-pre-wrap max-h-64 overflow-auto">{logs.join('\n') || 'Waiting for a scan...'}</pre>}
            </div>
          </div>
        )}

        {tab === 'results' && (
          <div>
            <div className="panel p-4 mb-4 flex flex-wrap gap-2 items-center">
              <input className="input" style={{ maxWidth: 260 }} placeholder="Search clips..." value={searchBox} onChange={(e) => setSearchBox(e.target.value)} />
              <select className="select" style={{ maxWidth: 180 }} value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
                <option>All</option>{Object.keys(CAT_COLORS).map((c) => <option key={c}>{c}</option>)}
              </select>
              <label className="text-sm">Min score: {scoreFilter}</label>
              <input type="range" min={0} max={10} step={0.5} value={scoreFilter} onChange={(e) => setScoreFilter(Number(e.target.value))} />
              <button className="btn-ghost" onClick={async () => { if (outDir) { const r = await call<{ summary?: { downloaded: number; failed: number } }>('download_all_clips', outDir); if (r?.summary) setToast(`${r.summary.downloaded} downloaded, ${r.summary.failed} failed.`) } }}>Download All Clips</button>
              <button className="btn-ghost" onClick={async () => { if (outDir) { const r = await call<{ summary?: { downloaded: number; failed: number } }>('download_all_images', outDir); if (r?.summary) setToast(`${r.summary.downloaded} images downloaded, ${r.summary.failed} failed.`) } }}>Download All Images</button>
              <button className="btn-ghost" onClick={async () => { if (outDir) await call('open_excel', outDir) }}>Open Excel</button>
              <button className="btn-ghost" onClick={async () => { if (outDir) await call('open_folder', outDir) }}>Open folder</button>
            </div>
            <div className="grid md:grid-cols-4 gap-4">
              <div className="panel p-4">
                <h3 className="font-bold mb-2">Moments</h3>
                <button className={`chip mb-2 ${selectedMoment === null ? 'active' : ''}`} onClick={() => setSelectedMoment(null)}>All moments</button>
                {momentOptions.map((m) => (
                  <button key={m.id} className={`block text-left w-full py-2 border-b border-white/10 text-sm ${selectedMoment === m.id ? 'text-cyan-300' : ''}`} onClick={() => setSelectedMoment(m.id)}>{m.id}. {m.line.slice(0, 60)}… ({m.count})</button>
                ))}
                {momentOptions.length === 0 && <p className="text-white/50 text-sm">No clips yet. Run a scan first.</p>}
              </div>
              <div className="md:col-span-3 space-y-3">
                {visibleClips.map((c, i) => (
                  <div key={i} className="panel p-4">
                    <div className="flex justify-between flex-wrap gap-2">
                      <span><span className="chip" style={{ borderColor: CAT_COLORS[c.category] || '#999', color: CAT_COLORS[c.category] || '#fff' }}>{c.category}</span> <b className="mono">{c.start_str} – {c.end_str}</b> · score <b>{c.score}</b></span>
                      <span className="text-sm"><button className="btn-ghost mr-2" onClick={() => window.open(c.clip_url, '_blank')}>▶ Watch clip</button>
                      <button className="btn-ghost mr-2" onClick={() => navigator.clipboard.writeText(c.clip_url)}>Copy link</button>
                      <button className="btn-ghost" onClick={async () => { if (outDir) { const idx = clips.indexOf(c); await call('set_clip_rejected', outDir, idx, true); setClips((cs) => cs.map((x, j) => j === idx ? { ...x, rejected: true } : x)) } }}>Reject (R)</button></span>
                    </div>
                    {c.video_id && <div className="mt-3"><iframe title={c.video_title} width="100%" height="260" src={`https://www.youtube-nocookie.com/embed/${c.video_id}?start=${Math.floor(c.start_s)}&end=${Math.floor(c.end_s)}`} allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen /></div>}
                    <p className="mt-2 font-semibold">{c.video_title} · {c.channel}</p>
                    <p className="text-sm text-white/70">{c.what_happens}</p>
                    <p className="text-sm italic text-white/60">“{c.key_quote}”</p>
                    <p className="text-xs text-white/50">{c.why_it_fits}</p>
                  </div>
                ))}
                {visibleClips.length === 0 && <p className="text-white/50">No clips match these filters.</p>}
              </div>
            </div>
          </div>
        )}

        {tab === 'images' && (
          <div className="panel p-4">
            <h2 className="font-bold text-lg mb-3">Images (Wikimedia + Openverse, no key)</h2>
            {images.length === 0 && <p className="text-white/50 text-sm">Images appear here after a scan with “Also find images” on.</p>}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {images.map((im, i) => (
                <button key={i} className="panel p-2 text-left" onClick={() => setSelectedImage(im)}>
                  <img src={String(im.url)} alt={String(im.title || '')} className="w-full h-32 object-cover rounded-lg" loading="lazy" />
                  <p className="text-xs mt-2 truncate">{String(im.title || '')}</p>
                  <p className="text-xs text-white/50">{String(im.source || '')} · {String(im.license || '')}</p>
                </button>
              ))}
            </div>
            {selectedImage && (
              <div className="panel p-4 mt-4">
                <h3 className="font-bold">{String(selectedImage.title || '')}</h3>
                <p className="text-sm">Source: {String(selectedImage.source || '')} · Author: {String(selectedImage.author || '')} · License: {String(selectedImage.license || '')}</p>
                <p className="text-sm mono break-words">Attribution: {String(selectedImage.attribution || '')}</p>
                <button className="btn-ghost mt-2" onClick={() => navigator.clipboard.writeText(String(selectedImage.attribution || ''))}>Copy attribution</button>
                <button className="btn-ghost mt-2 ml-2" onClick={() => setSelectedImage(null)}>Close</button>
              </div>
            )}
          </div>
        )}

        {tab === 'brain' && (
          <div className="grid md:grid-cols-5 gap-4">
            <div className="panel p-4 md:col-span-3">
              <h2 className="font-bold text-lg mb-2">Brain Lab — {brain === 'offline' ? 'Offline Brain (YAML rules)' : 'AI Brain (brain.txt)'}</h2>
              <textarea className="textarea mono" rows={22} value={brainText} onChange={(e) => setBrainText(e.target.value)} />
              <div className="flex gap-2 mt-3 flex-wrap">
                <button className="btn" onClick={async () => { const r = await call<{ ok: boolean; error?: string }>('save_brain', brainText, brain); setBrainMsg(r?.ok ? 'Saved. The next scan uses this brain.' : `Could not save: ${r?.error || 'unknown error'}`) }}>Save</button>
                <button className="btn-ghost" onClick={async () => loadBrain(brain)}>Reload</button>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ text: string }>('restore_brain', brain); if (r) { setBrainText(r.text); setBrainMsg('Default brain restored.') } }}>Restore default</button>
              </div>
              {brainMsg && <p className="text-sm mt-2">{brainMsg}</p>}
            </div>
            <div className="panel p-4 md:col-span-2">
              <h3 className="font-bold mb-2">Test on sample text</h3>
              <p className="text-sm text-white/60 mb-2">Only for Offline Brain. Shows which moments and phrases the rules detect.</p>
              <button className="btn-ghost" onClick={async () => { const r = await call<Record<string, unknown>>('test_brain', brainText); if (r) setBrainTest(r) }}>Test this brain on the sample</button>
              {brainTest && brainTest.ok === false && <p className="text-sm mt-2 text-red-300">{String(brainTest.error)}</p>}
              {brainTest && brainTest.ok === true && (
                <div className="mt-3 text-sm">
                  <p>Main subject: <b>{String(brainTest.main_subject)}</b></p>
                  {((brainTest.topics as { topic: string; search_queries: string[] }[]) || []).map((t, i) => (
                    <div key={i} className="border-b border-white/10 py-2"><b>{t.topic}</b><br /><span className="text-white/60">{t.search_queries.join(' · ')}</span></div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'settings' && (
          <div className="grid md:grid-cols-2 gap-4">
            <div className="panel p-4">
              <h3 className="font-bold mb-3">AI keys (optional)</h3>
              <p className="text-sm text-white/60 mb-3">Offline Brain needs no key. Only fill these in if you pick Gemini or Claude.</p>
              <label className="text-sm">Gemini key</label>
              <input className="input mb-3" type="password" defaultValue={String(settings.gemini_api_key || '')} onBlur={(e) => setSettings((s) => ({ ...s, gemini_api_key: e.target.value }))} placeholder="Paste a free Gemini key here" />
              <label className="text-sm">Claude key</label>
              <input className="input mb-3" type="password" defaultValue={String(settings.claude_api_key || '')} onBlur={(e) => setSettings((s) => ({ ...s, claude_api_key: e.target.value }))} placeholder="Paid Claude key (optional)" />
              <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean }>('test_key'); setToast(r?.ok ? 'Key works!' : 'Key test failed. Check the key and try again.') }}>Test key</button>
            </div>
            <div className="panel p-4">
              <h3 className="font-bold mb-3">Transcripts &amp; YouTube safe mode</h3>
              <label className="text-sm">Fallback speech model</label>
              <select className="select mb-3" value={String(settings.whisper_fallback_model || 'base')} onChange={(e) => setSettings((s) => ({ ...s, whisper_fallback_model: e.target.value }))}><option>base</option><option>small</option></select>
              <label className="text-sm">Max minutes to transcribe per video</label>
              <input className="input mb-3" type="number" defaultValue={Number(settings.whisper_max_minutes || 20)} onBlur={(e) => setSettings((s) => ({ ...s, whisper_max_minutes: Number(e.target.value) }))} />
              <label className="flex gap-2 items-center text-sm mb-3"><input type="checkbox" defaultChecked={Boolean(settings.safe_mode)} onChange={(e) => setSettings((s) => ({ ...s, safe_mode: e.target.checked }))} /> Safe mode (fewer YouTube requests, ON by default)</label>
              <label className="text-sm">Browser cookies (optional, secondary Google account)</label>
              <select className="select mb-3" value={String(settings.cookies_from_browser || '')} onChange={(e) => setSettings((s) => ({ ...s, cookies_from_browser: e.target.value }))}><option value="">None</option><option>chrome</option><option>edge</option><option>firefox</option></select>
              <label className="text-sm">Proxy address (optional)</label>
              <input className="input mb-3" placeholder="http://..." defaultValue={String(settings.proxy || '')} onBlur={(e) => setSettings((s) => ({ ...s, proxy: e.target.value }))} />
              <label className="text-sm">Results folder</label>
              <input className="input mb-3" defaultValue={String(settings.output_folder || '')} onBlur={(e) => setSettings((s) => ({ ...s, output_folder: e.target.value }))} />
              <div className="flex gap-2 flex-wrap">
                <button className="btn" onClick={async () => { await call('save_settings', settings); setToast('Settings saved.') }}>Save settings</button>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ message?: string }>('update_ytdlp'); setToast(r?.message || 'Update attempted.') }}>Update YouTube engine</button>
              </div>
            </div>
          </div>
        )}

        {tab === 'history' && (
          <div className="panel p-4">
            <h2 className="font-bold text-lg mb-3">Past runs</h2>
            {history.length === 0 && <p className="text-white/50 text-sm">No past runs yet.</p>}
            {history.map((h, i) => (
              <div key={i} className="flex justify-between border-b border-white/10 py-2">
                <span>{String(h.name)} · {String(h.main_subject || '')} · {Number(h.clips)} clips</span>
                <button className="btn-ghost" onClick={() => openRun(String(h.out_dir))}>Open</button>
              </div>
            ))}
          </div>
        )}
      </main>
      <footer className="px-5 pb-4 text-xs text-white/40">B-Roll Finder · Works offline with the Offline Brain. YouTube links open at the exact second. Uninstall keeps your results.</footer>
    </div>
  )
}
