import { ReactLenis } from 'lenis/react'
import 'lenis/dist/lenis.css'
import { Toaster } from 'sonner'
import { Nav } from './components/Nav'
import { Hero } from './components/Hero'
import { WorksWith } from './components/WorksWith'
import { Systematic } from './components/Systematic'
import { EditDemo } from './components/EditDemo'
import { Tour } from './components/Tour'
import { Features } from './components/Features'
import { Gallery } from './components/Gallery'
import { Guide } from './components/Guide'
import { Download } from './components/Download'
import { Help } from './components/Help'
import { Footer } from './components/Footer'
export default function App() {

  return (
    <ReactLenis root options={{ lerp: 0.12, anchors: { offset: -80 } }}>
      <a
        href="#systematic"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <div className="grain pointer-events-none fixed inset-0 z-[70] opacity-[0.035] mix-blend-multiply" />

      <main>
        <Hero />
        <Nav />
        <WorksWith />
        <Systematic />
        <EditDemo />
        <Tour />
        <Features />
        <Gallery />
        <Guide />
        <Download />
        <Help />
      </main>
      <Footer />
      <Toaster position="bottom-center" />
    </ReactLenis>
  )
}
