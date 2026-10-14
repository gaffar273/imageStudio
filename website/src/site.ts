// Names, links and facts the page uses. Downloads come from the GitHub release itself (see useRelease).

export const ORG = { name: 'AGS Labs', url: 'https://agslabs.tech' }
export const OWNER = 'gaffar273'
export const NAME = 'imageStudio'
export const REPO = `https://github.com/${OWNER}/${NAME}`

export const links = {
  repo: REPO,
  releases: `${REPO}/releases`,
  latest: `${REPO}/releases/latest`,
  watch: `${REPO}/subscription`,
  issues: `${REPO}/issues/new`,
  question: `${REPO}/issues/new?labels=question&title=${encodeURIComponent('Question: ')}`,
  readme: `${REPO}#readme`,
  source: `${REPO}#development`,
  doc: (path: string) => `${REPO}/blob/main/${path}`,
}

export const facts = {
  engine: '3.5 GB',
  cloudEngine: '60 MB',
  pipelines: 115,
  commands: 858,
}

export const clone = `git clone ${REPO}.git`

export const nav = [
  { id: 'systematic', label: 'How it edits' },
  { id: 'demos', label: 'Demos' },
  { id: 'features', label: 'Features' },
  { id: 'guide', label: 'Guide' },
  { id: 'download', label: 'Download' },
  { id: 'help', label: 'Help' },
] as const
