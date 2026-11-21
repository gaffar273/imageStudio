import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BookOpen, Check, Download, LifeBuoy, MessageSquare } from 'lucide-react'
import { Button, Em, GitHubIcon } from './components/ui'
import { LabsFooter } from './Labs'
import { products, glideDownloads } from './products'
import { useRelease } from './hooks/useRelease'
import './catalog.css'

function ProductLibrary() {
  return <section id="products" className="brand-section">
    <div className="section-line"><h2>Product <Em>library.</Em></h2><p>Explore the apps available from the studio.</p></div>
    <div className="project-stack">{products.map(product => {
      const path = '/product/' + product.slug
      return <article className={'project-spread ' + product.theme} key={product.slug}>
        <div className="project-story"><span className="project-category">{product.category}</span>
          <h3><a href={path}>{product.name}</a></h3><p>{product.description}</p>
          <ul>{product.features.map(feature => <li key={feature}><Check size={15}/>{feature}</li>)}</ul>
          <div className="project-actions"><Button variant="dark" href={path}>Explore {product.name}</Button><a href={path + '#guide'}>Read the guide</a></div>
        </div>
        <a className="project-visual" href={path} aria-label={'Explore ' + product.name}>
          <img className="product-screen" src={product.image} alt={product.alt} loading="lazy"/>
          {product.theme === 'studio' && <img className="sample-print" src="/media/gallery-lighthouse.webp" alt="" loading="lazy"/>}
          {product.theme === 'glide' && <div className="album-print" aria-hidden="true"><img src="/media/gallery-lake.webp" alt="" loading="lazy"/><span>Alpine morning</span></div>}
          <span className="visual-platform">{product.platform}</span>
        </a>
      </article>
    })}</div>
  </section>
}

const notebook = [
  {title:'Design notes', heading:'See how a tool works.', text:'Follow an edit from a written request to a finished layer, or trace how a phone sends a playback command to a laptop.', suffix:'walkthrough'},
  {title:'Source code', heading:'Look inside the build.', text:'Read the code that ships with each app. The repositories include setup instructions, architecture notes and the project history.', suffix:'source'},
  {title:'Release history', heading:'Follow each release.', text:'Check what changed in an update and find the files published with that version.', suffix:'releases'},
]

function StudioNotebook() {
  const [selected, setSelected] = useState(0)
  const note = notebook[selected]
  return <section id="studio" className="notebook"><div className="brand-section">
    <div className="section-line"><h2>Inside <Em>the lab.</Em></h2><p>Design decisions, code and releases from AGS Labs.</p></div>
    <div className="notebook-frame"><div className="notebook-tabs" role="group" aria-label="Studio resources">
      {notebook.map((item, i) => <button key={item.title} aria-pressed={selected===i} onClick={()=>setSelected(i)}>{item.title}</button>)}
    </div><div className="notebook-page"><h3>{note.heading}</h3><p>{note.text}</p>
      <div className="notebook-links">{products.map(p => <a key={p.slug} href={note.suffix === 'walkthrough' ? '/product/' + p.slug + p.walkthrough : p.repository + (note.suffix === 'source' ? '' : '/releases')}>{p.name + (note.suffix === 'walkthrough' ? ' walkthrough' : '')}</a>)}</div>
    </div></div>
  </div></section>
}

function Downloads() {
  const release = useRelease()
  return <section id="downloads" className="brand-section">
    <div className="section-line"><h2>Downloads<Em>.</Em></h2><p>Install a released build for your device.</p></div>
    <div className="release-table">{products.map(p => <article key={p.slug}>
      <div><h3>{p.name}</h3><span>{p.platform}</span></div>
      <div className="release-actions">
        {p.slug==='image-studio' && release.state==='ready' && release.windows ?
          <Button href={release.windows.url}><Download size={16}/> Windows installer</Button> :
          p.slug==='glideYT' ? <><Button href={glideDownloads.windows}><Download size={16}/> Windows installer</Button><Button href={glideDownloads.android}>Android APK</Button></> :
          <Button href={'/product/'+p.slug+'#download'}>Download options</Button>}
        <a href={p.repository+'/releases'}>Release notes</a>
      </div>
    </article>)}</div>
  </section>
}

function Home() {
  return <><a className="page-skip" href="#products">Skip to products</a><main className="brand-page">
    <section className="studio-mast"><div className="mast-inner">
      <div className="mast-type"><h1>AGS <Em>Labs.</Em></h1>
        <p className="studio-intro">An independent software studio building tools for the devices you use every day.</p>
        <div className="mast-actions"><Button variant="primary" size="lg" href="#products">Explore our products</Button><a href="#studio">Inside the lab</a></div>
      </div>
      <figure className="mast-art"><img src="/media/ags-studio-glass.webp" alt="Cobalt glass forms inspired by the AGS Labs mark" fetchPriority="high"/></figure>
    </div></section>
    <ProductLibrary/><StudioNotebook/><Downloads/>
    <section id="support" className="brand-support"><div className="brand-section"><div className="section-line"><h2>Guides &amp; <Em>support.</Em></h2><a href="/troubleshooting/windows/"><LifeBuoy size={18}/> Windows installation help</a></div>
      <div className="support-directory">{products.map(p=><article key={p.slug}><h3>{p.name}</h3><div>
        <a href={'/product/'+p.slug+'#guide'}><BookOpen size={16}/> Setup guide</a>
        <a href={p.repository+'/issues'}><MessageSquare size={16}/> Report an issue</a>
        <a href={p.repository}><GitHubIcon className="size-4"/> GitHub</a>
      </div></article>)}</div>
    </div></section>
  </main><LabsFooter/></>
}
createRoot(document.getElementById('root')!).render(<Home />)
