// Small bridge to the Python side (pywebview). In a plain browser preview
// there is no Python side, so calls fail softly instead of crashing the UI.
declare global { interface Window { pywebview?: { api: Record<string, (...a: unknown[]) => Promise<unknown>> } } }

export async function call<T>(name: string, ...args: unknown[]): Promise<T | null> {
  const api = window.pywebview?.api
  if (!api || typeof api[name] !== 'function') return null
  return (await api[name](...args)) as T
}
export const SAMPLE_SCRIPT = `In 2009, a 19-year-old Taylor Swift won her first MTV VMA, but Kanye West stormed the stage, grabbed the microphone and said Beyonce deserved the award. The moment went viral and started a feud that lasted for years. In 2019, Taylor lost the rights to her first six albums when Scooter Braun bought her old record label. Instead of giving up, she re-recorded all of them, and "Taylor's Version" became one of the biggest comebacks in music history.`
export const CAT_COLORS: Record<string, string> = {
  Scandal: '#E5534B', Controversy: '#F08C3B', 'Key Statement': '#5FA8E8',
  Interview: '#4CAF7D', 'News Report': '#A78BFA', 'Emotional Moment': '#EAB308',
  Reaction: '#F472B6', Performance: '#34D399', Background: '#9CA3AF',
}
export type Clip = { topic_id: number; script_line: string; category: string; score: number; start_s: number; end_s: number; start_str: string; end_str: string; clip_url: string; video_url: string; video_id: string; video_title: string; channel: string; what_happens: string; key_quote: string; why_it_fits: string; file?: string; rejected?: boolean }
