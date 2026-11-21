import { products } from './products'
import './index.css'
import './labs.css'

export function LabsHeader({ product = false }: { product?: boolean }) {
  return <header className="labs-header">
    <a className="labs-brand" href="/"><img src="/labs-icon.svg" alt="" width="34" height="34" />AGS Labs</a>
    <nav aria-label="Main navigation">
      <a href={product ? '/#products' : '#products'}>Products</a>
      {product && <a href="#guide">Guide</a>}
      <a href="/troubleshooting/windows/">Troubleshooting</a><a href="#support">Support</a>
    </nav>
  </header>
}

export function LabsFooter() {
  return <footer className="labs-footer"><a className="labs-brand" href="/">AGS Labs</a><span>© {new Date().getFullYear()} AGS Labs</span></footer>
}

export function Support() {
  return <section className="labs-support" id="support"><div><h2>Product support</h2><p>Ask a question or report a problem on GitHub.</p></div>
    <div className="support-links">{products.map(p => <a key={p.slug} href={p.repository + '/issues'}>{p.name} support</a>)}</div>
  </section>
}
