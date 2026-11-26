import './site-footer.js'

const catalog = fetch('/product-catalog.json').then(response => {
  if (!response.ok) throw new Error('Product catalog unavailable')
  return response.json()
}).catch(() => [])

class AgsNavigation extends HTMLElement {
  openedOnHover = false

  connectedCallback() {
    if (!this.shadowRoot) this.render()
    document.addEventListener('pointerdown', this.onOutside)
    document.addEventListener('keydown', this.onKeydown)
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this.onOutside)
    document.removeEventListener('keydown', this.onKeydown)
  }

  setMenuOpen(open, openedOnHover = false) {
    this.menu.open = open
    this.panel.inert = !open
    this.openedOnHover = openedOnHover
  }

  onOutside = event => {
    if (!event.composedPath().includes(this)) this.setMenuOpen(false)
  }

  onKeydown = event => {
    if (event.key !== 'Escape' || !this.menu.open) return
    const restoreFocus = this.menu.contains(this.shadowRoot.activeElement)
    this.setMenuOpen(false)
    if (restoreFocus) this.summary.focus()
  }

  render() {
    const root = this.attachShadow({mode: 'open'})
    root.innerHTML = `
      <link rel="stylesheet" href="/site-navigation.css">
      <nav aria-label="Main navigation">
        <a class="brand" href="/" aria-label="AGS Labs home"><img src="/labs-icon.svg" alt="" width="32" height="32">AGS Labs</a>
        <details><summary>Products<span class="chevron" aria-hidden="true"></span></summary>
          <div class="panel" inert><div class="entries"></div><a class="all" href="/#products">All products</a></div>
        </details>
        <a class="support" href="/support/">Support</a>
        <a class="download" href="/downloads/">Downloads</a>
      </nav>`
    this.menu = root.querySelector('details')
    this.summary = this.menu.querySelector('summary')
    this.panel = root.querySelector('.panel')

    this.menu.addEventListener('pointerenter', event => {
      if (event.pointerType !== 'mouse' || this.menu.open) return
      this.setMenuOpen(true, true)
    })
    this.menu.addEventListener('pointerleave', event => {
      if (event.pointerType === 'mouse' && this.openedOnHover && !this.panel.contains(root.activeElement)) {
        this.setMenuOpen(false)
      }
    })
    this.summary.addEventListener('click', event => {
      event.preventDefault()
      // A pointer click keeps a menu that already opened on hover open.
      const keepOpen = this.openedOnHover && event.detail > 0
      this.setMenuOpen(keepOpen || !this.menu.open)
    })

    catalog.then(products => {
      for (const product of products) {
        const link = document.createElement('a')
        link.href = '/product/' + encodeURIComponent(product.slug)
        link.textContent = product.name
        if (location.pathname.replace(/\/$/, '') === link.pathname) link.setAttribute('aria-current', 'page')
        const platform = document.createElement('small')
        platform.textContent = product.platform
        link.append(platform)
        root.querySelector('.entries').append(link)
      }
    })
    root.addEventListener('click', event => {
      if (event.target.closest('a')) this.setMenuOpen(false)
    })
    root.addEventListener('focusout', event => {
      if (!this.menu.contains(event.relatedTarget)) this.setMenuOpen(false)
    })
  }
}
customElements.define('ags-navigation', AgsNavigation)
