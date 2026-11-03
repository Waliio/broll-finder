import { useCallback, useEffect, useRef, useState } from 'react'
import { SAMPLE_SCRIPT, call, type Clip } from './api'

type Tab = 'mission' | 'live' | 'results' | 'images' | 'brain' | 'settings' | 'history'
type Moment = { id: number; topic: string; status: string; clips: number }
const STAGES = ['Transcribe', 'Plan', 'Search', 'Transcripts', 'Score', 'Export']

export default function App() {
  const [tab, setTab] = useState<Tab>('mission')
  const [script, setScript] = useState('')
  const [brain, setBrain] = useState('offline')
  const [isPublic, setIsPublic] = useState(false)
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
  const [selectedImage, setSelectedImage] = useState<Record<string, unknown> | null>(null)
  const [showLog, setShowLog] = useState(true)
  const [filePath, setFilePath] = useState('')
  const [catFilter, setCatFilter] = useState('All')
  const polling = useRef<number | null>(null)

  const loadSettings = useCallback(async () => {
    const s = await call<Record<string, unknown>>('get_settings')
    if (s) {
      setSettings(s); setBrain(String(s.ai_provider || 'offline'))
      setMoments(Number(s.max_moments || 15)); setVideosPer(Number(s.videos_per_moment || 4))
      setMinScore(Number(s.min_score || 6)); setFindImages(Boolean(s.also_find_images))
    }
  }, [])

  const loadBrain = useCallback(async (mode: string) => {
    if (isPublic) return
    const b = await call<{ text: string; ok?: boolean; error?: string }>('get_brain', mode)
    if (!b) { setBrainMsg('Could not load the brain. Close and reopen the app, then try Reload.'); return }
    if (b.ok === false) { setBrainMsg(`Could not load the brain: ${b.error || 'unknown error'}`); return }
    setBrainText(b.text); setBrainMsg('')
  }, [isPublic])

  const loadBuildMode = useCallback(async () => {
    const m = await call<{ public?: boolean }>('get_build_mode')
    if (m) setIsPublic(Boolean(m.public))
  }, [])

  const loadHistory = useCallback(async () => {
    const r = await call<{ runs: Record<string, unknown>[] }>('history')
    if (r) setHistory(r.runs || [])
  }, [])

  useEffect(() => { loadSettings(); loadBuildMode(); loadBrain('offline') }, [loadSettings, loadBuildMode, loadBrain])

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
        if (e.type === 'done') { setOutDir(String(e.out_dir || '')); setToast(`Done — ${Number(e.clips || 0)} clips saved.`) }
        if (e.type === 'error') setToast(String(e.text || 'Scan failed.'))
      }
    }, 1000)
    return () => { if (polling.current) window.clearInterval(polling.current) }
  }, [])

  const launch = async () => {
    setClips([]); setMomentList([]); setImages([]); setLogs([]); setOutDir('')
    const opts = { ai_provider: brain, max_moments: moments, videos_per_moment: videosPer, min_score: minScore, also_find_images: findImages, auto_download_clips: autoDownload, file_path: filePath }
    const r = await call<{ ok: boolean; error?: string }>('start_scan', script, opts)
    if (!r) { setToast('Scan could not start (no app backend).'); return }
    if (!r.ok) { setToast(r.error || 'Scan could not start.'); return }
    setTab('live'); setToast('Scan started — watch the Live screen.')
  }

  const tabs: Tab[] = isPublic
    ? ['mission', 'live', 'results', 'images', 'settings', 'history']
    : ['mission', 'live', 'results', 'images', 'brain', 'settings', 'history']
  const shownClips = clips.filter((c) => catFilter === 'All' || c.category === catFilter)
  const cats = ['All', ...Array.from(new Set(clips.map((c) => c.category)))]

  return (
    <div className="min-h-screen" style={{ background: '#071426' }}>
      <header className="relative overflow-hidden border-b border-line px-5 py-4">
        <div className="grid-texture absolute inset-0 opacity-40 pointer-events-none" />
        <div className="relative flex items-center justify-between">
          <div>
            <div className="text-xl font-black tracking-wide text-white">B-ROLL FINDER <span style={{ color: '#FF6A00' }}>◆ V2</span></div>
            <div className="text-xs" style={{ color: '#C7D6EA' }}>Paste a script. Get the exact YouTube moments. No API key needed.</div>
          </div>
          <div className="flex items-center gap-3">
            <span className="chip" style={status === 'Idle' ? {} : { background: '#FF6A00', color: '#fff', borderColor: '#FF6A00' }}>{status}</span>
            <span className="text-xs" style={{ color: '#C7D6EA' }}>Dark blue + orange edition</span>
          </div>
        </div>
      </header>

      <nav className="flex gap-2 px-5 py-3 flex-wrap">
        {tabs.map((t) => (
          <button key={t} className={`chip ${tab === t ? 'active' : ''}`} onClick={() => { setTab(t); if (t === 'history') loadHistory() }}>{t.toUpperCase()}</button>
        ))}
      </nav>

      {toast && <div className="mx-5 mb-3 panel p-3 text-sm">{toast} <button className="float-right" onClick={() => setToast('')}>✕</button></div>}

      <main className="px-5 pb-8 max-w-7xl mx-auto">
        {tab === 'mission' && (
          <div className="grid md:grid-cols-5 gap-4">
            <div className="panel p-4 md:col-span-3">
              <h2 className="font-bold text-lg mb-2">1. Your script</h2>
              <div className="border-2 border-dashed rounded-xl p-6 text-center mb-3" style={{ borderColor: 'rgba(255,106,0,0.45)' }}>
                <p className="mb-2">Choose an audio, video, .txt or .docx file, or paste the text below.</p>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean; path?: string; error?: string }>('choose_file'); if (r?.ok && r.path) { setFilePath(r.path); setToast(`File chosen: ${r.path}`) } else if (r) setToast(r.error || 'No file chosen.') }}>Choose file…</button>
                {filePath && <p className="text-xs mt-2 break-words">{filePath} <button className="underline" onClick={() => setFilePath('')}>Remove</button></p>}
                <p className="text-xs mt-2" style={{ color: '#C7D6EA' }}>Tip: the file is transcribed on your own PC. No upload, no key.</p>
              </div>
              <textarea className="textarea mono" rows={10} value={script} onChange={(e) => setScript(e.target.value)} placeholder="Paste your script text here..." />
              <button className="btn-ghost mt-3" onClick={() => setScript(SAMPLE_SCRIPT)}>Try with a sample script</button>
              <div className="text-xs mt-2" style={{ color: '#C7D6EA' }}>{script.split(/\s+/).filter(Boolean).length} words</div>
            </div>
            <div className="panel p-4 md:col-span-2">
              <h2 className="font-bold text-lg mb-3">2. Options</h2>
              <p className="text-sm mb-2" style={{ color: '#C7D6EA' }}>Brain (how it thinks)</p>
              <div className="flex gap-2 mb-4 flex-wrap">
                {(['offline', 'gemini', 'claude'] as const).map((b) => (
                  <button key={b} className={`chip ${brain === b ? 'active' : ''}`} onClick={() => { setBrain(b); loadBrain(b) }}>{b === 'offline' ? 'Offline (no key)' : b === 'gemini' ? 'Gemini (free key)' : 'Claude (paid key)'}</button>
                ))}
              </div>
              <label className="text-sm">Moments: {moments}</label>
              <input type="range" min={1} max={15} value={moments} onChange={(e) => setMoments(Number(e.target.value))} className="w-full accent-[#FF6A00]" />
              <label className="text-sm">Videos per moment: {videosPer}</label>
              <input type="range" min={1} max={8} value={videosPer} onChange={(e) => setVideosPer(Number(e.target.value))} className="w-full accent-[#FF6A00]" />
              <label className="text-sm">Minimum score: {minScore}</label>
              <input type="range" min={1} max={10} step={0.5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="w-full accent-[#FF6A00]" />
              <label className="flex gap-2 items-center mt-3 text-sm"><input type="checkbox" checked={findImages} onChange={(e) => setFindImages(e.target.checked)} /> Also find images</label>
              <label className="flex gap-2 items-center mt-2 text-sm"><input type="checkbox" checked={autoDownload} onChange={(e) => setAutoDownload(e.target.checked)} /> Auto-download clips</label>
              <button className="btn w-full mt-5 text-lg" onClick={launch}>▶ LAUNCH SCAN</button>
              <p className="text-xs mt-3" style={{ color: '#C7D6EA' }}>Step 1 of the test: open BRAIN first (private build) and check the rules are filled. Then run the sample scan here.</p>
            </div>
          </div>
        )}

        {tab === 'live' && (
          <div className="grid gap-4">
            <div className="panel p-4">
              <h2 className="font-bold text-lg mb-3">Pipeline</h2>
              <div className="flex flex-wrap gap-2">
                {STAGES.map((s) => <span key={s} className="chip" style={status === 'Scanning' ? { borderColor: '#FF6A00' } : {}}>{s}</span>)}
              </div>
              <p className="text-sm mt-3">Status: <b className="mono">{status}</b> · Requests used this run are capped at 40 (Safe Mode).</p>
              <div className="flex gap-2 mt-3">
                <button className="btn-ghost" onClick={async () => { await call('stop_scan'); setStatus('Idle') }}>Stop</button>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean; error?: string }>('resume_scan'); if (r && !r.ok) setToast(r.error || 'Nothing to resume.') }}>Resume</button>
              </div>
            </div>
            <div className="panel p-4">
              <h2 className="font-bold text-lg mb-2">Moment timeline</h2>
              {momentList.length === 0 && <p className="text-sm">Waiting for a scan…</p>}
              {momentList.map((m) => (
                <div key={m.id} className="flex justify-between border-b border-line py-2 text-sm">
                  <span><b className="mono">{m.id}</b> {m.topic}</span>
                  <span className="mono">{m.status} · {m.clips} clips</span>
                </div>
              ))}
            </div>
            <div className="panel p-4">
              <h2 className="font-bold text-lg mb-2">Live clip feed</h2>
              {clips.length === 0 && <p className="text-sm">No clips yet.</p>}
              {clips.slice(-10).map((c, i) => (
                <p key={i} className="text-sm py-1"><span className="mono" style={{ color: '#FF8C1A' }}>{c.start_str}–{c.end_str}</span> {c.topic} · {c.category} · <b className="mono">{c.score}</b></p>
              ))}
            </div>
            <div className="panel p-4">
              <button className="btn-ghost" onClick={() => setShowLog(!showLog)}>{showLog ? 'Hide log' : 'Show log'}</button>
              {showLog && <div className="mono text-xs mt-3 max-h-64 overflow-auto">{logs.map((l, i) => <p key={i}>{l}</p>)}</div>}
            </div>
          </div>
        )}

        {tab === 'results' && (
          <div className="grid gap-4">
            <div className="panel p-4 flex gap-2 flex-wrap items-center">
              <span className="text-sm">Category:</span>
              {cats.map((c) => <button key={c} className={`chip ${catFilter === c ? 'active' : ''}`} onClick={() => setCatFilter(c)}>{c}</button>)}
              <span className="ml-auto text-sm mono">{shownClips.length} clips</span>
            </div>
            {outDir && <div className="panel p-4 flex gap-2 flex-wrap">
              <button className="btn" onClick={async () => { const r = await call<{ ok: boolean; error?: string }>('download_all_clips', outDir); setToast(r?.ok ? 'Clips downloaded.' : (r?.error || 'Download failed.')) }}>Download All Clips</button>
              <button className="btn-ghost" onClick={async () => { await call('open_excel', outDir) }}>Open Excel</button>
              <button className="btn-ghost" onClick={async () => { await call('open_folder', outDir) }}>Open Folder</button>
            </div>}
            {shownClips.length === 0 && <div className="panel p-4 text-sm">No clips yet. Run a scan from Mission first.</div>}
            {shownClips.map((c, i) => (
              <div key={i} className="panel p-4">
                <div className="flex justify-between gap-3 flex-wrap">
                  <div>
                    <h3 className="font-bold">{c.topic}</h3>
                    <p className="text-sm">{c.video_title} · {c.channel}</p>
                    <p className="text-sm mono" style={{ color: '#FF8C1A' }}>{c.start_str} – {c.end_str} · {c.category} · Score {c.score}</p>
                    <p className="text-sm">{c.what_happens}</p>
                    <p className="text-sm italic">“{c.key_quote}”</p>
                  </div>
                  <button className="btn-ghost h-fit" onClick={async () => { await call('set_clip_rejected', outDir, c.clip_url, !c.rejected); setClips((cs) => cs.map((x) => x.clip_url === c.clip_url ? { ...x, rejected: !x.rejected } : x)) }}>{c.rejected ? 'Restore' : 'Reject'}</button>
                </div>
                {c.video_id && (
                  <iframe className="w-full mt-3 rounded-xl" height="315" title={c.video_title}
                    src={`https://www.youtube-nocookie.com/embed/${c.video_id}?start=${Math.floor(c.start)}&end=${Math.floor(c.end)}`}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen />
                )}
              </div>
            ))}
          </div>
        )}

        {tab === 'images' && (
          <div className="grid gap-4">
            <div className="panel p-4 text-sm">Images found during scans appear here (Wikimedia Commons + Openverse, commercial licences only by default, 1280px+). Click an image for its attribution.</div>
            <div className="grid md:grid-cols-3 gap-4">
              {images.map((im, i) => (
                <div key={i} className="panel p-3 cursor-pointer" onClick={() => setSelectedImage(im)}>
                  {String(im.url || '').match(/\.(jpg|jpeg|png|webp)/i) ? <img src={String(im.url)} alt={String(im.title || '')} className="rounded-lg w-full" /> : <p className="text-sm break-words">{String(im.url || '')}</p>}
                  <p className="text-sm mt-2 font-bold">{String(im.title || '')}</p>
                  <p className="text-xs">{String(im.source || '')} · {String(im.license || '')}</p>
                </div>
              ))}
            </div>
            {selectedImage && (
              <div className="panel p-4">
                <h3 className="font-bold">{String(selectedImage.title || '')}</h3>
                <p className="text-sm">Source: {String(selectedImage.source || '')} · Author: {String(selectedImage.author || '')} · License: {String(selectedImage.license || '')}</p>
                <p className="text-sm mono break-words">Attribution: {String(selectedImage.attribution || '')}</p>
                <button className="btn-ghost mt-2" onClick={() => navigator.clipboard.writeText(String(selectedImage.attribution || ''))}>Copy attribution</button>
                <button className="btn-ghost mt-2 ml-2" onClick={() => setSelectedImage(null)}>Close</button>
              </div>
            )}
          </div>
        )}

        {tab === 'brain' && !isPublic && (
          <div className="grid md:grid-cols-5 gap-4">
            <div className="panel p-4 md:col-span-3">
              <h2 className="font-bold text-lg mb-2">Brain Lab — {brain === 'offline' ? 'Offline Brain (YAML rules)' : 'AI Brain (brain.txt)'}</h2>
              <textarea className="textarea mono" rows={22} value={brainText} onChange={(e) => setBrainText(e.target.value)} />
              <div className="flex gap-2 mt-3 flex-wrap">
                <button className="btn" onClick={async () => { const r = await call<{ ok: boolean; error?: string }>('save_brain', brainText, brain); setBrainMsg(r?.ok ? 'Saved. The next scan uses this brain.' : `Could not save: ${r?.error || 'unknown error'}`) }}>Save</button>
                <button className="btn-ghost" onClick={async () => loadBrain(brain)}>Reload</button>
                <button className="btn-ghost" onClick={async () => { const r = await call<{ text: string; ok?: boolean; error?: string }>('restore_brain', brain); if (!r) { setBrainMsg('Restore failed: no reply from the app.') } else if (r.ok === false) { setBrainMsg(`Restore failed: ${r.error || 'unknown error'}`) } else { setBrainText(r.text); setBrainMsg('Default brain restored.') } }}>Restore default</button>
              </div>
              {brainMsg && <p className="text-sm mt-2">{brainMsg}</p>}
            </div>
            <div className="panel p-4 md:col-span-2">
              <h3 className="font-bold mb-2">Test on sample text</h3>
              <p className="text-sm mb-2" style={{ color: '#C7D6EA' }}>Only for Offline Brain. Shows which moments and phrases the rules detect. Expected: Taylor Swift, Kanye West vma award 2009, Scooter Braun bought rights 2019.</p>
              <button className="btn-ghost" onClick={async () => { const r = await call<Record<string, unknown>>('test_brain', brainText); if (r) setBrainTest(r) }}>Test this brain on the sample</button>
              {brainTest && brainTest.ok === false && <p className="text-sm mt-2" style={{ color: '#FF8C1A' }}>{String(brainTest.error)}</p>}
              {brainTest && brainTest.ok === true && (
                <div className="mt-3 text-sm">
                  <p>Main subject: <b>{String(brainTest.main_subject)}</b></p>
                  {((brainTest.topics as { topic: string; search_queries: string[] }[]) || []).map((t, i) => (
                    <div key={i} className="border-b border-line py-2"><b>{t.topic}</b><br /><span style={{ color: '#C7D6EA' }}>{t.search_queries.join(' · ')}</span></div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'settings' && (
          <div className="panel p-4 grid gap-3 max-w-2xl">
            <h2 className="font-bold text-lg">Settings</h2>
            {(Object.keys(settings) as string[]).filter((k) => !k.includes('api_key') || true).map((k) => (
              <label key={k} className="text-sm grid gap-1">
                <span>{k}</span>
                <input className="input" value={String(settings[k] ?? '')} onChange={(e) => setSettings((s) => ({ ...s, [k]: e.target.value }))} />
              </label>
            ))}
            <div className="flex gap-2 flex-wrap">
              <button className="btn" onClick={async () => { await call('save_settings', settings); setToast('Settings saved.') }}>Save settings</button>
              <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean; message?: string; error?: string }>('test_key'); setToast(r?.ok ? (r.message || 'Key works.') : (r?.error || 'Key test failed.')) }}>Test key</button>
              <button className="btn-ghost" onClick={async () => { const r = await call<{ ok: boolean }>('update_ytdlp'); setToast(r?.ok ? 'yt-dlp updated.' : 'yt-dlp update failed.') }}>Update yt-dlp</button>
            </div>
            {isPublic && <p className="text-sm" style={{ color: '#FF8C1A' }}>This is the public build: the BRAIN tab is hidden and the brain is locked.</p>}
          </div>
        )}

        {tab === 'history' && (
          <div className="panel p-4">
            <h2 className="font-bold text-lg mb-3">History</h2>
            {history.length === 0 && <p className="text-sm">No past runs yet.</p>}
            {history.map((r, i) => (
              <div key={i} className="flex justify-between border-b border-line py-2 text-sm flex-wrap gap-2">
                <span><b>{String(r.run_name || '')}</b> · <span className="mono">{Number(r.clips || 0)} clips</span></span>
                <span className="flex gap-2">
                  <button className="btn-ghost" onClick={async () => { const d = await call<{ ok: boolean; clips?: Clip[]; images?: Record<string, unknown>[] }>('get_run', String(r.out_dir || '')); if (d?.ok) { setClips(d.clips || []); setImages(d.images || []); setOutDir(String(r.out_dir || '')); setTab('results') } }}>Open</button>
                  <button className="btn-ghost" onClick={async () => { await call('open_folder', String(r.out_dir || '')) }}>Folder</button>
                </span>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
