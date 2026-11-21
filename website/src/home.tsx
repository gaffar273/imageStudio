import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Aperture, BookOpen, Download, LifeBuoy, Smartphone } from 'lucide-react'
import { Button, Em, GitHubIcon } from './components/ui'
import { LabsFooter, LandingHero } from './Labs'
import { RemoteDemo } from './RemoteDemo'
import { products } from './products'
import './catalog.css'

const prints = [
  {id:'seaside', title:'Seaside town', detail:'Terracotta rooftops over the Mediterranean'},
  {id:'fox', title:'Winter fox', detail:'A red fox in a snowy pine forest'},
  {id:'lighthouse', title:'Lighthouse', detail:'A red lighthouse on a rocky shore at sunset'},
]

function Workbench() {
  const [product, setProduct] = useState('image-studio')
  const [index, setIndex] = useState(0)
  const picture = prints[index]
  return <div className="workbench">
    <div className="bench-toolbar"><div role="group" aria-label="Product preview" className="segmented">
      {products.map(p => <button key={p.slug} aria-pressed={product === p.slug} onClick={()=>setProduct(p.slug)}>
        {p.slug === 'image-studio' ? <Aperture size={16}/> : <Smartphone size={16}/>} {p.name}</button>)}
    </div><span className="bench-caption">Product preview</span></div>
    {product === 'image-studio' ? <div className="print-workspace">
      <figure className="big-print"><img src={'/media/gallery-' + picture.id + '.webp'} alt={picture.detail}/><figcaption>{picture.title}</figcaption></figure>
      <div className="print-selector"><span>Image library</span>{prints.map((p,i)=><button key={p.id} aria-label={p.title} aria-pressed={index === i} onClick={()=>setIndex(i)}>
        <img src={'/media/gallery-' + p.id + '.webp'} alt=""/><span>{p.title}</span></button>)}</div>
    </div> : <RemoteDemo/>}
  </div>
}

function Home() {
  return <><a className="page-skip" href="#products">Skip to products</a><main>
    <LandingHero label={<><img src="/labs-icon.svg" alt=""/> AGS Labs</>} title="Make a picture." accent="Cue a video."
      lead="Create and edit pictures with Image Studio. With GlideYT, pick a video on your phone and play it on your laptop."
      actions={<><Button variant="primary" size="lg" href="#products">Explore the products</Button><Button size="lg" href="#preview">Try a preview</Button></>}>
      <div id="preview"><Workbench/></div>
    </LandingHero>
    <section className="landing-section" id="products"><div className="section-head"><h2>Our <Em>products.</Em></h2></div>
      <div className="product-pair">{products.map(p=><article className="catalog-product" key={p.slug}>
        <a href={'/product/'+p.slug} className={'product-art '+p.slug} aria-label={'Explore '+p.name}>
          {p.slug==='image-studio' ? <img src="/media/app-create.webp" alt="Image Studio’s Create workspace" loading="lazy"/> : <img src="/media/glide-remote.png" alt="GlideYT’s Android remote" loading="lazy"/>}
        </a><div className="product-copy"><small>{p.platform}</small><h3><a href={'/product/'+p.slug}>{p.name}</a></h3><p>{p.description}</p>
        <div className="product-actions"><Button variant="dark" href={'/product/'+p.slug}>Explore {p.name}</Button><a href={'/product/'+p.slug+'#download'}><Download size={16}/> Downloads</a></div></div>
      </article>)}</div>
    </section>
    <section id="support" className="support-band"><div className="support-inner"><div><LifeBuoy size={28}/><h2>Product <Em>support.</Em></h2><a href="/troubleshooting/windows/">Windows installation troubleshooting</a></div>
      <div className="support-list">{products.map(p=><div key={p.slug}><strong>{p.name}</strong><a href={'/product/'+p.slug+'#guide'}><BookOpen size={16}/> Guide</a><a href={p.repository+'/issues'}><GitHubIcon className="size-4"/> Issues</a></div>)}</div>
    </div></section>
    </main><LabsFooter/></>
}
createRoot(document.getElementById('root')!).render(<Home />)
