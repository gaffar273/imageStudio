import { useState } from 'react'
import { MonitorPlay, Repeat1, Search, SlidersHorizontal } from 'lucide-react'
import { Em } from './components/ui'
import './glide-tour.css'

const views = [
  { name:'Search', icon:Search, title:'Choose the next video on your phone.', body:'Search for a title while your video plays. Tap Now playing at the bottom of the results, tap the same video, or use Android Back to return to the player at its current position.', region:'search' },
  { name:'Playback', icon:MonitorPlay, title:'See what is playing across the room.', body:'Drag the timeline to preview a timestamp. Lift your finger to seek on the laptop, or use the ten-second buttons to skip forward or back.', region:'playback' },
  { name:'Listening modes', icon:Repeat1, title:'Listen on repeat or set a bedtime.', body:'Repeat 1 loops the current track. Shuffle changes the order of a supported playlist. Set a sleep timer for 15, 30 or 60 minutes to pause the laptop even with your phone screen off.', region:'modes' },
  { name:'Player settings', icon:SlidersHorizontal, title:'Adjust the player from your seat.', body:'Speed, quality and volume sit below the playback controls. The disconnect button is above Search. For controls in a hidden browser tab, choose Set up background controls once on Windows and play in the dedicated YouTube window.', region:'settings' },
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
