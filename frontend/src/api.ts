// Bridge to the Python side (pywebview). In a plain browser preview
// there is no Python side, so calls return null instead of crashing.
declare global { interface Window { pywebview?: { api: Record<string, (...a: unknown[]) => Promise<unknown>> } } }

export async function call<T>(name: string, ...args: unknown[]): Promise<T | null> {
  const api = window.pywebview?.api
  if (!api || typeof api[name] !== 'function') return null
  try {
    return (await api[name](...args)) as T
  } catch {
    return null
  }
}

export const SAMPLE_SCRIPT = `In 2009, a 19-year-old Taylor Swift won her first MTV VMA, but Kanye West stormed the stage, grabbed the microphone and said Beyonce deserved the award. The moment went viral and started a feud that lasted for years. In 2019, Taylor lost the rights to her first six albums when Scooter Braun bought her old record label. Instead of giving up, she re-recorded all of them, and "Taylor's Version" became one of the biggest comebacks in music history.`

export type Clip = {
  topic_id: number; topic: string; script_line: string; category: string; score: number;
  start: number; end: number; start_str: string; end_str: string; clip_url: string;
  video_url: string; video_id: string; video_title: string; channel: string;
  what_happens: string; key_quote: string; why_it_fits: string; rejected?: boolean
}
