import { useEffect, useState } from 'react'
import { Laptop, Pause, Play, RotateCcw, RotateCw, Wifi } from 'lucide-react'

const duration = 100
const clock = (time: number) => Math.floor(time / 60) + ':' + String(time % 60).padStart(2, '0')

export function RemoteDemo() {
  const [position, setPosition] = useState(24)
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => setPosition(value => Math.min(duration, value + 1)), 1000)
    return () => window.clearInterval(timer)
  }, [playing])
  useEffect(() => { if (position === duration) setPlaying(false) }, [position])

  function toggle() {
    if (position === duration) setPosition(0)
    setPlaying(!playing)
  }
  return <div className="remote-demo" role="group" aria-label="Interactive GlideYT playback demo">
    <div className="demo-monitor">
      <div className="window-label"><Laptop size={16}/> Laptop preview</div>
      <div className="video-scene">
        <img src="/media/gallery-lake.webp" alt="An alpine lake surrounded by snowy mountains" style={{transform:'scale(' + (1 + position / 650) + ')'}}/>
        <div className="video-caption"><span>Alpine morning</span><small>{clock(position)} / {clock(duration)}</small>
          <div className="time-track"><i style={{width:position + '%'}}/></div>
        </div>
      </div>
    </div>
    <div className="demo-phone">
      <div className="earpiece" aria-hidden="true"/>
      <div className="phone-id"><img src="/media/glide-mark.png" alt=""/>GlideYT</div>
      <span className="demo-connection"><Wifi size={13}/> Demo laptop</span>
      <img className="phone-thumb" src="/media/gallery-lake.webp" alt=""/>
      <strong>Alpine morning</strong><span className="phone-status">{playing ? 'Playing' : position === duration ? 'Finished' : 'Paused'}</span>
      <input aria-label="Demo playback position" type="range" min="0" max={duration} value={position} onChange={e=>setPosition(Number(e.target.value))}/>
      <div className="remote-buttons">
        <button aria-label="Back ten seconds" onClick={()=>setPosition(p=>Math.max(0,p-10))}><RotateCcw/></button>
        <button className="play-key" aria-label={playing ? 'Pause demo' : 'Play demo'} onClick={toggle}>{playing ? <Pause/> : <Play/>}</button>
        <button aria-label="Forward ten seconds" onClick={()=>setPosition(p=>Math.min(duration,p+10))}><RotateCw/></button>
      </div>
    </div>
  </div>
}
