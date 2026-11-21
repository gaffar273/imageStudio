// Shared by the React pages and the static help and privacy pages.
const destinations = [
  ['Home', '/'],
  ['Image Studio', '/product/image-studio'],
  ['GlideYT', '/product/glideYT'],
  ['Troubleshooting', '/troubleshooting/windows/'],
]
const current = location.pathname.replace(/\/$/, '')
const links = destinations.map(([name, url]) => {
  const active = current === url.replace(/\/$/, '') ? ' aria-current="page"' : ''
  return '<a href="' + url + '"' + active + '>' + name + '</a>'
}).join('')

class AgsNavigation extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return
    const root = this.attachShadow({mode: 'open'})
    root.innerHTML = `
      <link rel="stylesheet" href="/site-navigation.css">
      <nav aria-label="Main navigation">
        <a class="brand" href="/"><img src="/labs-icon.svg" alt="" width="32" height="32">AGS Labs</a>
        <div class="pages">${links}</div>
        <details class="downloads"><summary>Downloads <span aria-hidden="true">⌄</span></summary>
          <div class="panel"><a href="/product/image-studio#download">Image Studio downloads</a><a href="/product/glideYT#download">GlideYT downloads</a></div>
        </details>
        <details class="mobile"><summary aria-label="Navigation menu"><i></i><i></i><i></i></summary><div class="panel">${links}</div></details>
      </nav>`
    const menus = [...root.querySelectorAll('details')]
    for (const menu of menus) {
      menu.addEventListener('toggle', () => {
        if (menu.open) for (const other of menus) if (other !== menu) other.open = false
      })
    }
    const close = () => menus.forEach(menu => { menu.open = false })
    this.outside = event => { if (!event.composedPath().includes(this)) close() }
    document.addEventListener('pointerdown', this.outside)
    root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) close() })
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        const menu = menus.find(item => item.open)
        if (menu) { menu.open = false; menu.querySelector('summary').focus() }
      }
    })
    root.addEventListener('click', event => { if (event.target.closest('a')) close() })
  }
  disconnectedCallback() { document.removeEventListener('pointerdown', this.outside) }
}
customElements.define('ags-navigation', AgsNavigation)
