import { useState } from 'react'
import { ImageIcon } from 'lucide-react'
import Lightbox from 'yet-another-react-lightbox'
import Captions from 'yet-another-react-lightbox/plugins/captions'
import 'yet-another-react-lightbox/styles.css'
import 'yet-another-react-lightbox/plugins/captions.css'
import { Marquee } from '@/components/ui/marquee'
import { Em, Intro } from './ui'
import { pictures, type Picture } from '@/content'

const rowA = pictures.slice(0, 5)
const rowB = pictures.slice(5)

export function Gallery() {
  const [open, setOpen] = useState(-1)
  const tile = (p: Picture) => (
    <button
      key={p.id}
      type="button"
      onClick={() => setOpen(pictures.indexOf(p))}
      className="group/tile relative h-[230px] shrink-0 cursor-zoom-in overflow-hidden rounded-[22px] bg-tint shadow-card sm:h-[280px]"
      style={{ aspectRatio: `${p.w} / ${p.h}` }}
      aria-label={`Enlarge: ${p.prompt}`}
    >
      <img
        src={`media/gallery-${p.id}.webp`}
        alt={p.prompt}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-cover transition-transform duration-700 group-hover/tile:scale-[1.04]"
      />
      <span className="absolute inset-x-2 bottom-2 translate-y-2 rounded-2xl bg-black/55 p-3 text-left opacity-0 backdrop-blur-md transition-all duration-300 group-hover/tile:translate-y-0 group-hover/tile:opacity-100">
        <span className="line-clamp-2 text-[12.5px] leading-snug text-white">{p.prompt}</span>
        <span className="mt-1.5 block font-mono text-[11px] text-white/65">
          {p.model} · {p.time}
        </span>
      </span>
    </button>
  )

  return (
    <section id="gallery" className="scroll-mt-24 overflow-hidden py-24 sm:py-32">
      <div className="px-4 sm:px-5">
        <Intro
          badge={
            <>
              <ImageIcon className="size-3.5 text-accent" /> Made with Image Studio
            </>
          }
          title={
            <>
              Every picture here <Em>started as a sentence.</Em>
            </>
          }
          lead="Straight out of the app on one laptop graphics card. Hover a picture to read its prompt, or open it full size."
        />
      </div>
      <div className="mt-14 space-y-1 [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]">
        <Marquee pauseOnHover repeat={3} className="[--duration:70s] [--gap:1rem]">
          {rowA.map(tile)}
        </Marquee>
        <Marquee pauseOnHover reverse repeat={3} className="[--duration:80s] [--gap:1rem]">
          {rowB.map(tile)}
        </Marquee>
      </div>
      <Lightbox
        open={open >= 0}
        index={Math.max(open, 0)}
        close={() => setOpen(-1)}
        plugins={[Captions]}
        captions={{ descriptionTextAlign: 'center' }}
        slides={pictures.map((p) => ({
          src: `media/gallery-${p.id}.webp`,
          width: p.w,
          height: p.h,
          alt: p.prompt,
          title: `${p.model} · ${p.time}`,
          description: p.prompt,
        }))}
        styles={{ container: { backgroundColor: 'rgba(17,17,19,0.94)' } }}
      />
    </section>
  )
}
