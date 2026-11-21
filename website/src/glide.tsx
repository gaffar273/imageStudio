import { createRoot } from 'react-dom/client'
import { Download } from 'lucide-react'
import { LabsHeader, LabsFooter } from './Labs'
import { glideRepository, glideDownloads } from './products'

const steps = [
  ['Set up the laptop', <>Run <strong>GlideYT-Setup.exe</strong> on a 64-bit Windows PC and follow the installer. Open <strong>GlideYT</strong> from Start. Setup includes the runtime and the phone APK. Use Edge or Chrome for YouTube.</>],
  ['Install the phone remote', <>On an arm64 phone running Android 7 or later, download the Android APK. You can also choose <strong>Install Android app</strong> on the laptop and scan its code with your phone camera. Open the APK and follow Android’s installation prompts.</>],
  ['Pair over Wi-Fi', <>Join the same trusted Wi-Fi on both devices. Choose <strong>Show pairing code</strong> on Windows, then <strong>Scan QR code</strong> inside GlideYT on Android. The pairing code is valid for five minutes.</>],
  ['Play a video', <>Choose <strong>Open YouTube</strong> on Windows. Search on the phone and tap a result. Use the phone to pause, resume or skip ten seconds while the video plays on the laptop.</>],
] as const

function Glide() {
  return <div className="labs-shell glide-page"><a className="labs-skip" href="#guide">Skip to setup guide</a><LabsHeader product />
    <main><section className="glide-hero" id="download"><div className="glide-copy">
      <a href="/#products" className="catalog-back">All products</a>
      <h1>GlideYT</h1><p className="glide-lead">Your phone, <em>the remote.</em></p>
      <p>Control YouTube on your Windows laptop from your Android phone over Wi-Fi.</p>
      <div className="download-actions"><a className="labs-btn" href={glideDownloads.windows}><Download size={17}/> Download for Windows</a><a className="labs-btn secondary" href={glideDownloads.android}><Download size={17}/> Android APK</a></div>
      <div className="inline-links"><a href="#guide">Setup guide</a><a href={glideRepository}>GitHub source</a><a href={glideRepository + '/releases'}>Release notes</a></div>
    </div><figure className="phone-stage"><img src="/media/glide-remote.png" alt="GlideYT on Android showing the playback timeline, pause, skip and volume controls" width="310" height="620"/></figure></section>
    <section id="guide" className="glide-section"><div><h2>Setup guide</h2><p>Start with the laptop, then pair your phone.</p></div>
      <ol className="steps">{steps.map(([heading,body]) => <li key={heading}><div><h3>{heading}</h3><p>{body}</p></div></li>)}</ol>
    </section>
    <section id="support" className="glide-section"><div><h2>Help & contact</h2><p>Get help with pairing and playback.</p></div><div className="glide-help">
      <p><a href="/troubleshooting/windows/">Windows download and installation troubleshooting</a></p><details><summary>My phone can’t reach the laptop</summary><p>Check that both devices use the same trusted Wi-Fi. Guest networks may isolate devices. In Windows settings inside GlideYT, choose <strong>Allow Wi-Fi access</strong> for the private network, then show a fresh pairing code.</p></details>
      <details><summary>YouTube opens but playback won’t start</summary><p>Click Play on the laptop once so the browser can expose its media controls. For playlist, speed or quality controls while YouTube is in the background, follow the <a href={glideRepository + '#background-controls'}>background controls guide</a>.</p></details>
      <details><summary>Android can’t update my test installation</summary><p>Uninstall the earlier test APK, install the public release, then pair again. Public releases use the AGS Labs signing key.</p></details>
      <p>For anything else, include your Windows and Android versions and what happened. Keep pairing codes private.</p>
      <a className="labs-btn secondary" href={glideRepository + '/issues'}>Contact GlideYT support</a>
    </div></section></main><LabsFooter /></div>
}
createRoot(document.getElementById('root')!).render(<Glide />)
