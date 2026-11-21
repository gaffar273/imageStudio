import type { ReactNode } from 'react'
import { Em } from './components/ui'
import { products } from './products'
import './index.css'
import './labs.css'

export function LandingHero({ label, title, accent, lead, actions, note, children }: {
  label: ReactNode; title: string; accent: string; lead: string; actions: ReactNode; note?: ReactNode; children: ReactNode
}) {
  return <section className="landing-hero">
    <div className="dots hero-field" aria-hidden="true"/>
    <div className="hero-intro">
      <div className="hero-label">{label}</div>
      <h1>{title} <Em>{accent}</Em></h1><p className="hero-lead">{lead}</p>
      <div className="landing-actions">{actions}</div>
      {note && <p className="release-note">{note}</p>}
    </div>
    <div className="hero-stage">{children}</div>
  </section>
}

export function LabsFooter() {
  return <footer className="landing-footer"><a href="/"><img src="/labs-icon.svg" alt="" width="26" height="26"/> AGS Labs</a>
    <div>{products.map(p => <a key={p.slug} href={'/product/' + p.slug}>{p.name}</a>)}<a href="/troubleshooting/windows/">Installation help</a></div>
  </footer>
}
