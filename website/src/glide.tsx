import { createRoot } from 'react-dom/client'
import { BookOpen, Download, Laptop, MonitorPlay, ScanLine, Search, Smartphone, Wifi } from 'lucide-react'
import { Button, Em, GitHubIcon } from './components/ui'
import { LandingHero, LabsFooter } from './Labs'
import { RemoteDemo } from './RemoteDemo'
import { GlideTour } from './GlideTour'
import { glideRepository, glideDownloads } from './products'

const steps = [
  ['Set up the laptop', <>Run <strong>GlideYT-Setup.exe</strong> on a 64-bit Windows PC and follow the installer. Open <strong>GlideYT</strong> from Start. Setup includes the runtime and the phone APK. Use Edge or Chrome for YouTube.</>],
  ['Install the phone remote', <>On an arm64 phone running Android 7 or later, download the Android APK. You can also choose <strong>Install Android app</strong> on the laptop and scan its code with your phone camera. Open the APK and follow Android’s installation prompts.</>],
  ['Pair over Wi-Fi', <>Join the same trusted Wi-Fi on both devices. Choose <strong>Show pairing code</strong> on Windows, then <strong>Scan QR code</strong> inside GlideYT on Android. Center the code inside the green camera frame to pair. The code is valid for five minutes.</>],
  ['Play a video', <>Choose <strong>Open YouTube</strong> on Windows. Search on the phone and tap a result. While it plays, tap <strong>Suggested</strong> to browse recommendations. Tap one to play it in the same laptop tab. Drag the timeline to seek on the laptop. After searching, tap <strong>Now playing</strong> to return to the current video and keep your place.</>],
] as const

const controls = [
  { icon: Search, title: 'Find your next video', text: 'Browse search results or open Suggested for recommendations from the video you’re watching. Tap Now playing to return to it, or choose another result to play it on the laptop.' },
  { icon: MonitorPlay, title: 'Keep the big screen playing', text: 'Tap the timeline to jump to a moment, or drag to preview a timestamp and release to seek. The ten-second skip buttons are there for smaller jumps.' },
  { icon: Wifi, title: 'Pair over home Wi-Fi', text: 'Scan the laptop’s code once. Your phone remembers the connection, and you can remove it in Windows settings.' },
]

function Glide() {
  return <><a className="page-skip" href="#guide">Skip to setup guide</a><main>
    <LandingHero label={<><span className="glide-emblem"><img src="/media/glide-mark.png" alt=""/></span> GlideYT</>}
      title="Pick it here." accent="Play it there."
      lead="Search YouTube on your Android phone. Press play and watch it on your Windows laptop, from anywhere on your home Wi-Fi."
      actions={<><Button variant="primary" size="lg" href={glideDownloads.windows}><Download size={18}/> Download for Windows</Button>
        <Button size="lg" href={glideDownloads.android}><Smartphone size={18}/> Android APK</Button></>}
      note={<><a href="#guide">Setup guide</a><span> · </span><a href={glideRepository + '/releases'}>Release notes</a></>}>
      <div className="demo-heading"><span>Try the remote</span><p>Choose a scene below, then use the phone to play, pause or scrub the laptop preview.</p></div>
      <RemoteDemo/>
    </LandingHero>
    <section className="landing-section"><div className="section-head"><h2>One phone. <Em>One laptop.</Em></h2></div>
      <div className="feature-grid">{controls.map(c=><article key={c.title}><span className="feature-icon"><c.icon/></span><h3>{c.title}</h3><p>{c.text}</p></article>)}</div>
    </section>
    <GlideTour/>
    <section id="guide" className="tinted-section"><div className="landing-section"><div className="section-head"><BookOpen/><h2>From install <Em>to first play.</Em></h2></div>
      <ol className="guide-grid">{steps.map(([title,body],i)=><li key={title}><span className="step-number">{i+1}</span><h3>{title}</h3><p>{body}</p></li>)}</ol>
    </div></section>
    <section id="download" className="landing-section"><div className="section-head"><h2>Get <Em>GlideYT.</Em></h2></div>
      <div className="download-grid"><article><Laptop/><h3>Windows companion</h3><p>64-bit Windows · EXE installer</p><Button variant="primary" href={glideDownloads.windows}><Download size={17}/> Download installer</Button></article>
      <article><Smartphone/><h3>Android remote</h3><p>Android 7 or later · arm64 APK</p><Button href={glideDownloads.android}><Download size={17}/> Download APK</Button></article></div>
    </section>
    <section id="support" className="tinted-section"><div className="landing-section help-layout"><div><div className="section-head left"><h2>Questions, <Em>answered.</Em></h2><p>Help with installation, pairing and playback.</p></div>
      <div className="help-links"><a href="/troubleshooting/windows/"><Laptop/> Windows installation help</a><a href={glideRepository+'/issues'}><ScanLine/> Contact GlideYT support</a><a href={glideRepository}><GitHubIcon className="size-4"/> Source on GitHub</a></div></div>
      <div className="faqs">
        <details><summary>Where are Repeat and Shuffle?</summary><p>Repeat 1 appears for tracks the laptop can loop. Open a supported playlist to use Shuffle. If the browser does not expose these controls through Windows, use Connect background controls in GlideYT settings. For a timed pause, open Sleep timer on your phone.</p></details>
        <details><summary>Why does my phone appear several times?</summary><p>Older versions saved each pairing as “My Android.” Update GlideYT on Windows and Android, then open the phone app once. Windows shows your phone by model and reuses that entry when you pair again. You can remove obsolete entries by date under <strong>Earlier pairings</strong>.</p></details>
        <details><summary>My phone can’t reach the laptop</summary><p>Check that both devices use the same trusted Wi-Fi. Guest networks may isolate devices. In Windows settings inside GlideYT, choose <strong>Allow Wi-Fi access</strong> for the private network, then show a fresh pairing code.</p></details>
      <details><summary>How do I control YouTube while using another tab?</summary><p>Open GlideYT settings on Windows, choose <strong>Connect background controls</strong> and approve the browser prompt. Leave the YouTube tab open while you browse. If the connection drops, GlideYT retries the saved tab.</p></details>
      <details><summary>YouTube opens but playback won’t start</summary><p>Click Play on the laptop once so the browser can expose its media controls. For playlist, speed or quality controls while YouTube is in the background, follow the <a href={glideRepository + '#background-controls'}>background controls guide</a>.</p></details>
      <details><summary>Android can’t update my test installation</summary><p>Uninstall the earlier test APK, install the public release, then pair again. Public releases use the AGS Labs signing key.</p></details>
      </div></div></section>
    </main><LabsFooter variant="glide"/></>
}
createRoot(document.getElementById('root')!).render(<Glide />)
