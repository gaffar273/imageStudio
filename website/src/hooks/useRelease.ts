import { useEffect, useState } from 'react'
import { NAME, OWNER } from '@/site'

export type Asset = { url: string; name: string; size: string }

export type Release =
  | { state: 'loading' }
  | { state: 'none' } // nothing published yet, or GitHub could not be reached
  | { state: 'ready'; version: string; date: string; page: string; windows?: Asset; linux?: Asset }

const KEY = 'image-studio-release'
const MAX_AGE = 10 * 60 * 1000

type GitHubRelease = {
  tag_name: string
  html_url: string
  published_at: string
  draft: boolean
  prerelease: boolean
  assets: { name: string; browser_download_url: string; size: number }[]
}

function megabytes(bytes: number) {
  return `${Math.round(bytes / 1024 / 1024)} MB`
}

function parse(data: GitHubRelease): Release {
  const asset = (test: (name: string) => boolean): Asset | undefined => {
    const a = data.assets.find((x) => test(x.name.toLowerCase()))
    return a && { url: a.browser_download_url, name: a.name, size: megabytes(a.size) }
  }
  return {
    state: 'ready',
    version: data.tag_name.replace(/^v/, ''),
    date: new Date(data.published_at).toLocaleDateString('en', { day: 'numeric', month: 'long', year: 'numeric' }),
    page: data.html_url,
    windows: asset((n) => n.endsWith('.exe')),
    linux: asset((n) => n.endsWith('.tar.gz')),
  }
}

function cached(): Release | null {
  try {
    const c = JSON.parse(sessionStorage.getItem(KEY) ?? 'null')
    return c && Date.now() - c.at < MAX_AGE ? c.release : null
  } catch {
    return null
  }
}

// One request per page load, shared by every component that asks.
let pending: Promise<Release> | null = null

function load(): Promise<Release> {
  pending ??= fetch(`https://api.github.com/repos/${OWNER}/${NAME}/releases?per_page=10`, {
    headers: { Accept: 'application/vnd.github+json' },
  })
    .then((r) => (r.ok ? (r.json() as Promise<GitHubRelease[]>) : []))
    .then((list) => {
      const latest = list.find((x) => !x.draft && !x.prerelease)
      return latest ? parse(latest) : ({ state: 'none' } as Release)
    })
    .catch(() => ({ state: 'none' }) as Release)
    .then((release) => {
      try {
        sessionStorage.setItem(KEY, JSON.stringify({ at: Date.now(), release }))
      } catch {
        /* storage unavailable */
      }
      return release
    })
  return pending
}

/** The latest published release on GitHub. Until one exists the page offers to watch the repository instead. */
export function useRelease(): Release {
  const [release, setRelease] = useState<Release>(() => cached() ?? { state: 'loading' })
  useEffect(() => {
    if (release.state !== 'loading') return
    let live = true
    load().then((r) => live && setRelease(r))
    return () => {
      live = false
    }
  }, [release.state])
  return release
}
