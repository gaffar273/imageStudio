import './site-footer.js'

const catalog = fetch('/product-catalog.json').then(response => {
  if (!response.ok) throw new Error('Product catalog unavailable')
  return response.json()
}).catch(() => [])

class AgsNavigation extends HTMLElement {
  connectedCallback() {
    if (!this.shadowRoot) this.render()
    document.addEventListener('pointerdown', this.onOutside)
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this.onOutside)
  }

  onOutside = event => {
    if (!event.composedPath().includes(this)) this.menu.open = false
  }

  render() {
    const root = this.attachShadow({mode: 'open'})
    root.innerHTML = `
      <link rel="stylesheet" href="/site-navigation.css">
      <nav aria-label="Main navigation">
        <a class="brand" href="/" aria-label="AGS Labs home"><img src="/labs-icon.svg" alt="" width="32" height="32">AGS Labs</a>
        <details><summary>Products<span class="chevron" aria-hidden="true"></span></summary>
          <div class="panel"><div class="entries"></div><a class="all" href="/#products">All products</a></div>
        </details>
        <a class="support" href="/#support">Support</a>
        <a class="download" href="/#downloads">Downloads</a>
      </nav>`
    this.menu = root.querySelector('details')
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
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape' && this.menu.open) {
        this.menu.open = false
        this.menu.querySelector('summary').focus()
      }
    })
    root.addEventListener('click', event => {
      if (event.target.closest('a')) this.menu.open = false
    })
    root.addEventListener('focusout', event => {
      if (!this.menu.contains(event.relatedTarget)) this.menu.open = false
    })
  }
}
customElements.define('ags-navigation', AgsNavigation)
