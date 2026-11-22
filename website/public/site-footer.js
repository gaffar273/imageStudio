const imageRepo = 'https://github.com/gaffar273/imageStudio'
const glideRepo = 'https://github.com/gaffar273/GlideYT'
const views = {
  studio: {
    name:'AGS Labs', description:'Independent software for the devices you use every day.',
    heading:'', accent:'', actions:[],
    index:[['Inside the lab','/#studio'],['Products','/#products'],['Downloads','/downloads/'],['Support','/support/']],
    resources:[['Windows installation help','/troubleshooting/windows/'],['Image Studio privacy','/privacy/']],
  },
  image: {
    name:'Image Studio', description:'A desktop app for making and editing pictures with models that run on your own graphics card.',
    heading:'Your next picture is', accent:'one sentence away.',
    actions:[['Download for Windows','#download'],['View the code',imageRepo]],
    index:[['How it edits','#systematic'],['Demos','#demos'],['Features','#features'],['Guide','#guide'],['Download','#download'],['Help','#help']],
    resources:[['Source code',imageRepo],['Releases',imageRepo+'/releases'],['Report a problem',imageRepo+'/issues/new'],['Privacy','/privacy/'],['AGS Labs','/']],
  },
  glide: {
    name:'GlideYT', description:'A phone remote for YouTube on your Windows laptop.',
    heading:'Your laptop,', accent:'within reach.',
    actions:[['Download for Windows','/downloads/glideyt/586037dc0cba/GlideYT-Setup.exe'],['Android APK',glideRepo+'/releases/latest/download/GlideYT-Android.apk']],
    index:[['Remote tour','#tour'],['Setup guide','#guide'],['Downloads','#download'],['Help','#support']],
    resources:[['Source code',glideRepo],['Release notes',glideRepo+'/releases'],['Report a problem',glideRepo+'/issues'],['Windows installation help','/troubleshooting/windows/']],
  },
}
function links(items) {
  return items.map(([name, href]) => '<a href="'+href+'">'+name+'</a>').join('')
}
class AgsFooter extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return
    const variant = this.getAttribute('variant') || 'studio'
    const view = views[variant] || views.studio
    const root = this.attachShadow({mode:'open'})
    const prints = ['seaside','fox','umbrella','chef','lake','shelter','lighthouse']
    const icon = variant==='image' ? '/image-studio-icon.svg' : variant==='glide' ? '/media/glide-mark.png' : '/labs-icon.svg'
    const showInvitation = variant === 'image' || variant === 'glide'
    root.innerHTML = `
      <link rel="stylesheet" href="/site-footer.css">
      <footer>${showInvitation ? `<div class="prints" aria-hidden="true">${prints.map((id,i)=>'<img loading="lazy" alt="" style="rotate:'+((i%2?1:-1)*(2+i%3))+'deg" src="/media/gallery-'+id+'.webp">').join('')}</div>
        <div class="invitation"><h2>${view.heading} <em>${view.accent}</em></h2>
          <div class="actions"><slot name="actions">${links(view.actions)}</slot></div></div>` : ''}
        <div class="columns"><div><div class="identity"><img class="${variant}" src="${icon}" alt="">${view.name}</div><p>${view.description}</p></div>
        <div><h3>${variant==='studio'?'Studio':'On this page'}</h3>${links(view.index)}</div>
        <div><h3>${variant==='studio'?'Resources':'Project'}</h3>${links(view.resources)}</div></div>
        <div class="end"><span>© ${new Date().getFullYear()} AGS Labs</span><a href="/">agslabs.tech</a></div>
      </footer>`
  }
}
customElements.define('ags-footer', AgsFooter)
