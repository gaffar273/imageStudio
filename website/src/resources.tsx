import { createRoot } from 'react-dom/client'
import { Button } from './components/ui'
import { LabsFooter } from './Labs'
import { products, glideDownloads, rillboardDownloads, rillboardVersion } from './products'
import { useRelease } from './hooks/useRelease'
import './resources.css'

function Installers({ slug, repository }: { slug: string; repository: string }) {
  const release = useRelease()
  if (slug === 'glideYT') return <>
    <Button variant="dark" href={glideDownloads.windows}>Windows installer</Button>
    <Button href={glideDownloads.android}>Android APK</Button>
  </>
  if (slug === 'rillboard') return <>
    <Button variant="dark" href={rillboardDownloads.installer} download>Windows installer ZIP</Button>
    <Button href={rillboardDownloads.standalone} download>Standalone EXE</Button>
    <Button href={rillboardDownloads.deb} download>Ubuntu / Debian installer</Button>
    <Button href={rillboardDownloads.portable} download>Other Linux desktops</Button>
  </>
  if (slug === 'image-studio' && release.state === 'ready' && release.windows) {
    return <Button variant="dark" href={release.windows.url}>Windows installer</Button>
  }
  return <Button variant="dark" href={repository + '/releases/latest'}>View release downloads</Button>
}

function ResourcePage({ support }: { support: boolean }) {
  return <><a className="page-skip" href="#main">Skip to content</a>
    <main id="main" className="resource-page">
      <header><h1>{support ? 'Support' : 'Downloads'}<em>.</em></h1>
        <p>{support ? 'Find a setup guide or contact the studio about a problem with your app.' : 'Get the latest release for your device.'}</p>
      </header>
      <div className="resource-list">{products.map(product =>
        <article key={product.slug}>
          <div><h2>{product.name}</h2><p>{product.platform}{!support && product.slug === 'rillboard' && ` · ${rillboardVersion}`}</p></div>
          <div className="resource-actions">{support ?
            <><Button variant="dark" href={'/product/' + product.slug + '#guide'}>Setup guide</Button>
              <Button href={product.repository + '/issues'}>Report an issue</Button></> :
            <><Installers slug={product.slug} repository={product.repository} />
              <a className="resource-link" href={product.slug === 'rillboard' ? '/product/rillboard#release-notes' : product.repository + '/releases'}>Release notes</a></>}
          </div>
        </article>)}</div>
      <a className="resource-link" href="/troubleshooting/windows/">Troubleshoot a Windows installation</a>
    </main><LabsFooter /></>
}
createRoot(document.getElementById('root')!).render(<ResourcePage support={location.pathname.startsWith('/support')} />)
