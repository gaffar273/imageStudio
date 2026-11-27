import { createRoot } from 'react-dom/client'
import { Download, FolderOpen, GraduationCap, Pencil } from 'lucide-react'
import { LandingHero, LabsFooter } from './Labs'
import { Button, Em } from './components/ui'
import { rillboardDownloads, rillboardRepository } from './products'
import './rillboard.css'

const features = [
  { Icon: Pencil, title: 'Draw and diagram', detail: 'Write with a pen or mouse, arrange shapes and arrows, or plot functions on graph paper.' },
  { Icon: FolderOpen, title: 'Keep editable boards', detail: 'Organize boards into folders on your PC. Export a drawing as PNG, SVG, or PDF when you need to share it.' },
  { Icon: GraduationCap, title: 'Work through lessons', detail: 'A connected assistant can add explanations, diagrams, and practice questions. Scroll back through earlier steps and add your own notes.' },
]

function Rillboard() {
  return <>
    <a className="page-skip" href="#main">Skip to content</a>
    <main id="main" className="rillboard-page">
      <LandingHero
        label={<><img className="rillboard-mark" src="/rillboard-icon.svg" alt="" width="44" height="44" /> Rillboard</>}
        title="Sketch ideas."
        accent="Work them out."
        lead="Draw offline and save editable boards on Windows and Linux. Optional live teaching is available on Windows."
        actions={<>
          <Button variant="primary" size="lg" href={rillboardDownloads.installer}><Download size={18} aria-hidden="true" /> Download for Windows</Button>
          <Button size="lg" href={rillboardDownloads.deb}>Download for Ubuntu / Debian (.deb)</Button>
          <Button size="lg" href={rillboardDownloads.standalone}>Standalone EXE</Button>
        </>}
        note={<><a href="#guide">Setup guide</a> · <a href={rillboardRepository + '/releases'}>Release notes</a></>}
      >
        <figure id="workspace" className="rillboard-preview">
          <img
            src="/media/rillboard-workspace.png"
            width="1280"
            height="820"
            alt="Rillboard’s Windows workspace, with drawing tools above the canvas and shortcuts to start drawing or open a board"
          />
        </figure>
      </LandingHero>

      <section className="landing-section" aria-labelledby="features-title">
        <div className="section-head"><h2 id="features-title">Tools for <Em>the whole board.</Em></h2></div>
        <div className="feature-grid">
          {features.map(({ Icon, title, detail }) => <article key={title}>
            <span className="feature-icon"><Icon aria-hidden="true" /></span>
            <h3>{title}</h3><p>{detail}</p>
          </article>)}
        </div>
      </section>

      <section id="guide" className="tinted-section" aria-labelledby="guide-title">
        <div className="landing-section">
          <div className="section-head"><h2 id="guide-title">Set up <Em>Rillboard.</Em></h2></div>
          <div className="rillboard-guide">
            <article>
              <h3>Install on Windows</h3>
              <p>Extract <strong>Rillboard-Windows.zip</strong> and run <strong>Install Drawing.cmd</strong> to create Desktop and Start menu shortcuts. You can also run <strong>Rillboard.exe</strong> directly.</p>
              <p>Requires 64-bit Windows 10 or 11, .NET Framework 4.8, and the Microsoft Edge WebView2 Runtime.</p>
            </article>
            <article>
              <h3>Install on Linux</h3>
              <p>On Ubuntu, Debian or Mint, open the <a href={rillboardDownloads.deb}>.deb installer</a> with your software installer, choose <strong>Install</strong>, then open Rillboard from Applications.</p>
              <p>Other desktops: extract the <a href={rillboardDownloads.portable}>portable archive</a> and run <code>sh rillboard/linux/install.sh</code>. Linux requires Python 3 and a desktop browser.</p>
            </article>
            <article>
              <h3>Connect live teaching on Windows</h3>
              <p>With Node.js 18 or later installed, open <strong>Settings</strong> in Rillboard. Under <strong>Live teaching</strong>, choose <strong>Add plugin</strong>, then <strong>Set up</strong> to connect your assistant.</p>
              <a href={rillboardRepository + '/blob/main/TEACHER.md'}>Read the teaching guide</a>
            </article>
          </div>
          <div className="rillboard-links">
            <a href={rillboardRepository}>Source on GitHub</a>
            <a href={rillboardRepository + '/issues'}>Report an issue</a>
          </div>
        </div>
      </section>
    </main>
    <LabsFooter />
  </>
}

createRoot(document.getElementById('root')!).render(<Rillboard />)
