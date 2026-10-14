import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FolderOpen, KeyRound, Layers, PackageOpen, PenLine, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AppWindow, Em, Intro } from './ui'

const screens = [
  {
    id: 'create',
    icon: Sparkles,
    title: 'Create',
    text: 'Describe the picture, pick a model and a size, and generate. Ctrl + Enter works from anywhere on the screen.',
    points: ['Four local models, or a cloud one', 'Smart prompt tidies short ideas', 'A sketch can guide the layout'],
  },
  {
    id: 'edit',
    icon: PenLine,
    title: 'Edit',
    text: 'Drop in a photo, paste one, or pick a recent picture, then say what to change. Paint an area to keep the edit inside it.',
    points: ['Before and After on one click', 'Keep editing carries on from the result', 'Undo a painted stroke with Ctrl + Z'],
  },
  {
    id: 'photocraft',
    icon: Layers,
    title: 'PhotoCraft studio',
    text: 'Describe a whole retouch at once. The plan lands as named layers in a real PSD, and the result is checked against what you asked.',
    points: ['115 ready-made pipelines', 'Every PhotoCraft command, with controls', 'Export to PSD, TIFF, PNG, JPEG or WebP'],
  },
  {
    id: 'library',
    icon: FolderOpen,
    title: 'Library',
    text: 'Every picture with the prompt and settings that made it. Search the words, or search by what is in the picture.',
    points: ['Use these settings loads a picture back into Create', 'Favorites and sorting', 'Plain files in a folder you choose'],
  },
  {
    id: 'providers',
    icon: KeyRound,
    title: 'Providers',
    text: 'No NVIDIA card? Connect OpenAI, Gemini, fal.ai or Replicate with your own key. The editing assistant can run on Claude, GPT, Ollama or LM Studio.',
    points: ['Keys encrypted for your Windows account', 'Test connection lists the models a key reaches', 'Cloud pictures land in the same library'],
  },
  {
    id: 'models',
    icon: PackageOpen,
    title: 'Models',
    text: 'Install each model with one click. Downloads come straight from the maker and pick up where they left off.',
    points: ['Progress, pause and resume', 'Shows what fits your graphics card', 'Finds PhotoCraft and Krita if installed'],
  },
]

export function Tour() {
  const [active, setActive] = useState(0)
  const refs = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.index))
      },
      { rootMargin: '-48% 0px -48% 0px' },
    )
    refs.current.forEach((el) => el && observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <section id="tour" className="scroll-mt-24 border-y border-line bg-card px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <Sparkles className="size-3.5 text-accent" /> A tour of the app
          </>
        }
        title={
          <>
            One window, from idea <Em>to finished file.</Em>
          </>
        }
        lead="Screens captured from the app itself, in its light theme."
      />

      <div className="mx-auto mt-16 grid max-w-[1180px] grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[360px_minmax(0,1fr)] lg:gap-14">
        <div>
          {screens.map((s, i) => (
            <div
              key={s.id}
              ref={(el) => {
                refs.current[i] = el
              }}
              data-index={i}
              className="flex flex-col justify-center py-6 lg:min-h-[64vh] lg:py-0"
            >
              <div className={cn('transition-opacity duration-500', active === i ? 'opacity-100' : 'lg:opacity-35')}>
                <span className="flex items-center gap-3">
                  <span
                    className={cn(
                      'grid size-10 place-items-center rounded-xl border transition-colors duration-500',
                      active === i ? 'border-accent bg-accent text-white' : 'border-line bg-tint text-body',
                    )}
                  >
                    <s.icon className="size-[18px]" />
                  </span>
                  <span className="font-mono text-[12.5px] text-muted">
                    {String(i + 1).padStart(2, '0')} / {String(screens.length).padStart(2, '0')}
                  </span>
                </span>
                <h3 className="mt-5 text-[28px] font-semibold tracking-[-0.03em]">{s.title}</h3>
                <p className="mt-3 text-[16px] leading-relaxed text-body">{s.text}</p>
                <ul className="mt-5 space-y-2">
                  {s.points.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-[14.5px] text-body">
                      <span className="mt-2 size-1.5 shrink-0 rounded-full bg-accent" /> {p}
                    </li>
                  ))}
                </ul>
              </div>
              {/* On small screens each step shows its own screenshot */}
              <AppWindow className="mt-6 lg:hidden">
                <img src={`media/app-${s.id}.webp`} alt={`The ${s.title} screen`} loading="lazy" className="block w-full" />
              </AppWindow>
            </div>
          ))}
        </div>

        <div className="relative hidden lg:block">
          <div className="sticky top-[calc(50vh-300px)]">
            <AppWindow>
              <div className="relative aspect-[2000/1175]">
                <AnimatePresence initial={false}>
                  <motion.img
                    key={screens[active].id}
                    src={`media/app-${screens[active].id}.webp`}
                    alt={`The ${screens[active].title} screen`}
                    initial={{ opacity: 0, scale: 1.01 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.45 }}
                    className="absolute inset-0 h-full w-full object-cover object-top"
                  />
                </AnimatePresence>
              </div>
            </AppWindow>
            <div className="mt-5 flex justify-center gap-1.5">
              {screens.map((s, i) => (
                <button
                  key={s.id}
                  type="button"
                  aria-label={`Go to ${s.title}`}
                  onClick={() => refs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className={cn('h-1.5 rounded-full transition-all', i === active ? 'w-6 bg-ink' : 'w-1.5 bg-line-strong hover:bg-muted')}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
