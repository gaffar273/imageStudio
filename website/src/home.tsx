import { createRoot } from 'react-dom/client'
import { Aperture, Disc3, Download, LifeBuoy } from 'lucide-react'
import { LabsHeader, LabsFooter, Support } from './Labs'
import { products } from './products'
import './catalog.css'

function Cover({ studio }: { studio: boolean }) {
  if (studio) return <div className="showcase studio-showcase" aria-hidden="true">
    <img className="studio-screen" src="/media/app-create.webp" alt="" loading="lazy"/>
    <div className="studio-print"><img src="/media/gallery-fox.webp" alt="" loading="lazy"/></div>
    <div className="studio-print second-print"><img src="/media/gallery-lighthouse.webp" alt="" loading="lazy"/></div>
  </div>
  return <div className="showcase remote-showcase" aria-hidden="true">
    <div className="deck-disc"><div><Disc3 size={26}/></div></div>
    <img className="showcase-phone" src="/media/glide-remote.png" alt="" loading="lazy"/>
  </div>
}

function Home() {
  return <div className="labs-shell catalog-home">
    <a className="labs-skip" href="#products">Skip to products</a><LabsHeader/>
    <main>
      <section className="studio-hero">
        <img className="hero-scene" src="/media/ags-desktop.webp" alt="" fetchPriority="high"/>
        <div className="hero-copy">
          <h1>Make it.<br/><em>Play it.</em></h1>
          <p>Image Studio brings your pictures to life. GlideYT puts your laptop’s playback in your hand.</p>
          <div className="hero-products"><a href="/product/image-studio"><Aperture size={17}/> Image Studio</a><a href="/product/glideYT"><img src="/media/glide-mark.png" alt=""/> GlideYT</a></div>
        </div>
      </section>
      <section id="products" className="collection">
        <div className="collection-heading"><h2>Products<span>.</span></h2><a href="/troubleshooting/windows/"><LifeBuoy size={16}/> Installation help</a></div>
        <div className="edition-grid">{products.map(p => <article className={'edition ' + p.slug} key={p.slug}>
          <a className="edition-cover" href={'/product/' + p.slug} aria-label={'Explore ' + p.name}><Cover studio={p.slug === 'image-studio'}/></a>
          <div className="edition-info"><div className="product-identity">
            <span className="identity-icon">{p.slug === 'image-studio' ? <Aperture/> : <img src="/media/glide-mark.png" alt=""/>}</span>
            <div><span className="platform">{p.platform}</span><h3><a href={'/product/' + p.slug}>{p.name}</a></h3></div>
          </div><p>{p.description}</p>
          <div className="edition-actions"><a className="labs-btn" href={'/product/' + p.slug}>Explore {p.name}</a><a href={'/product/' + p.slug + '#download'}><Download size={16}/> Downloads</a></div></div>
        </article>)}</div>
      </section>
      <Support/>
    </main><LabsFooter/>
  </div>
}
createRoot(document.getElementById('root')!).render(<Home />)
