import { useState } from 'react'
import { MonitorPlay, Search, SlidersHorizontal } from 'lucide-react'
import { Em } from './components/ui'
import './glide-tour.css'

const views = [
  { name:'Search', icon:Search, title:'Choose the next video on your phone.', body:'Enter a title in Search YouTube. Browsing results leaves the current video playing on the laptop. Tap the result you want to open it there.', region:'search' },
  { name:'Playback', icon:MonitorPlay, title:'See what is playing across the room.', body:'The remote shows the title, playing state and timeline. Pause for a moment, resume, or skip ten seconds in either direction.', region:'playback' },
  { name:'Player settings', icon:SlidersHorizontal, title:'Adjust the player from your seat.', body:'Volume, speed and quality controls live below the timeline. For controls in a hidden browser tab, choose Connect background controls on Windows and approve the browser prompt.', region:'settings' },
]

export function GlideTour() {
  const [selected, setSelected] = useState(0)
  const view = views[selected]
  return <section id="tour" className="landing-section glide-tour">
    <div className="section-head"><h2>Inside <Em>the remote.</Em></h2><p>Explore the controls on the Android app.</p></div>
    <div className="tour-frame"><div className="tour-screen">
      <div className="device-capture"><img src="/media/glide-remote.png" alt="The GlideYT Android remote with search, timeline, playback controls and settings"/>
        <div className={'tour-highlight '+view.region} aria-hidden="true"/></div>
    </div><div className="tour-notes"><div className="tour-choices" role="group" aria-label="Remote controls">
      {views.map((item,index)=><button key={item.name} aria-pressed={index===selected} onClick={()=>setSelected(index)}><item.icon size={17}/>{item.name}</button>)}
    </div><div className="tour-description"><h3>{view.title}</h3><p>{view.body}</p></div></div></div>
  </section>
}
