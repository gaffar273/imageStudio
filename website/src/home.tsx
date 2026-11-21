import { createRoot } from 'react-dom/client'
import { LabsFooter } from './Labs'
import { products } from './products'
import './catalog.css'

type Product = (typeof products)[number]

function ProductCover({ product }: { product: Product }) {
  return <a className={'work-cover ' + product.theme} href={'/product/' + product.slug}>
    <div className="work-picture">
      {product.theme === 'studio' &&
        <img className="work-backdrop" src="/media/gallery-seaside.webp" alt="" loading="lazy" />}
      {product.theme === 'glide' &&
        <img className="work-backdrop" src="/media/gallery-lake.webp" alt="" loading="lazy" />}
      <img className="work-screen" src={product.image} alt={product.alt} loading="lazy" />
    </div>
    <div className="work-caption">
      <span className="work-platform">{product.platform}</span>
      <h3>{product.name}</h3>
      <p>{product.summary}</p>
      <span className="work-link">Explore {product.name}</span>
    </div>
  </a>
}

function Home() {
  return <>
    <a className="page-skip" href="#studio">Skip to studio introduction</a>
    <main className="studio-home">
      <header className="studio-cover">
        <div className="cover-type">
          <h1>AGS <em>Labs.</em></h1>
          <div className="cover-intro">
            <p>An independent software studio for the devices you already own.</p>
            <a href="#products">Explore our work</a>
          </div>
        </div>
        <img className="cover-art" src="/media/studio-workbench.webp" alt="A cobalt-blue workbench with drafting tools, a keyboard and a machined orange dial" width="1536" height="1024" fetchPriority="high" />
      </header>

      <div id="studio" className="studio-letter">
        <h2>From the <em>studio.</em></h2>
        <div><p>We start with things we wish our own devices could do.</p>
          <p>What if a picture could go from a sentence to an editable layer, all on your PC? What if the phone on the sofa could run the video playing across the room? Those questions became our first apps. We share the code alongside each one.</p>
        </div>
      </div>

      <section id="products" className="selected-work" aria-labelledby="work-title">
        <h2 id="work-title">Our <em>products.</em></h2>
        <div className="work-grid">
          {products.map(product => <ProductCover key={product.slug} product={product} />)}
        </div>
      </section>
    </main>
    <LabsFooter />
  </>
}

function routeLegacyHash() {
  if (location.hash === '#downloads' || location.hash === '#support') {
    location.replace('/' + location.hash.slice(1) + '/')
  }
}
routeLegacyHash()
window.addEventListener('hashchange', routeLegacyHash)
createRoot(document.getElementById('root')!).render(<Home />)
