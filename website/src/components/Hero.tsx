import { useEffect, useRef, useState } from 'react'
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
  type MotionValue,
} from 'motion/react'
import { ArrowDownToLine, ArrowRight, Check, ChevronDown, Cpu, Eye, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Em, GitHubIcon } from './ui'
import { byId, type Picture } from '@/content'
import { links } from '@/site'
import { useRelease } from '@/hooks/useRelease'

const reel = ['seaside', 'umbrella', 'market', 'baking', 'neon'].map(byId)
const steps: Record<string, number> = { 'RealVisXL 5.0': 30, 'Z-Image Turbo': 9, 'SDXL Turbo': 4 }

const prints: { id: string; className: string; rotate: number; depth: number }[] = [
  { id: 'fox', className: 'left-[1%] top-[2%] w-[168px]', rotate: -7, depth: 1.1 },
  { id: 'chef', className: 'left-[-2%] top-[42%] w-[146px]', rotate: 4, depth: 0.7 },
  { id: 'lighthouse', className: 'left-[-1%] bottom-[0%] w-[140px]', rotate: -3, depth: 1.4 },
  { id: 'fisherman', className: 'right-[2%] top-[0%] w-[150px]', rotate: 6, depth: 1.2 },
  { id: 'lake', className: 'right-[-1%] top-[46%] w-[164px]', rotate: -5, depth: 0.8 },
]

export function Hero() {
  const release = useRelease()
  const ref = useRef<HTMLDivElement>(null)
  const mx = useSpring(useMotionValue(0), { stiffness: 60, damping: 18 })
  const my = useSpring(useMotionValue(0), { stiffness: 60, damping: 18 })

  return (
    <section
      id="top"
      ref={ref}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        mx.set((e.clientX - r.left) / r.width - 0.5)
        my.set((e.clientY - r.top) / r.height - 0.5)
      }}
      className="relative overflow-hidden pt-32 pb-20 sm:pt-40"
    >
      {/* soft dot field and a warm glow behind the card */}
      <div className="dots pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_70%_55%_at_50%_30%,black,transparent)]" />
      <div className="pointer-events-none absolute top-[38%] left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgb(255_196_150/0.35),rgb(147_180_255/0.18),transparent)] blur-2xl" />

      <div className="relative mx-auto max-w-[1180px] px-5">
        <motion.div
          initial={{ opacity: 0, y: 12, filter: 'blur(8px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto max-w-[860px] text-center"
        >
          <ReleaseBadge release={release} />
          <h1 className="mt-6 text-[48px] leading-[0.98] font-semibold tracking-[-0.045em] sm:text-[76px] lg:text-[92px]">
            Write it. <Em>Watch it develop.</Em>
          </h1>
          <p className="mx-auto mt-6 max-w-[56ch] text-[17px] leading-relaxed text-body sm:text-[19px]">
            Image Studio makes pictures from a sentence and edits photos when you describe the change. It runs the
            models on your own graphics card and keeps every file on your PC.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            {release.state === 'ready' && release.windows ? (
              <Button variant="primary" size="lg" href={release.windows.url}>
                <ArrowDownToLine className="size-[18px]" /> Download for Windows
              </Button>
            ) : (
              <Button variant="dark" size="lg" href={links.watch} target="_blank" rel="noreferrer">
                <Eye className="size-[18px]" /> Watch for the release
              </Button>
            )}
            <Button size="lg" href="#demos">
              See it work <ArrowRight className="size-[18px] transition-transform group-hover/btn:translate-x-0.5" />
            </Button>
          </div>
          <p className="mt-4 text-[13.5px] text-muted">
            {release.state === 'ready' && release.windows
              ? `Version ${release.version} · ${release.windows.size} · Windows 10 and 11, 64-bit`
              : release.state === 'none'
                ? 'The Windows installer is on its way. Until then, it runs from the source on GitHub.'
                : 'Free for Windows 10 and 11, 64-bit'}
          </p>
        </motion.div>

        <div className="relative mt-14 sm:mt-16">
          <div className="pointer-events-none absolute inset-y-[-40px] inset-x-[-20px] hidden xl:block">
            {prints.map((p, i) => (
              <Print key={p.id} picture={byId(p.id)} {...p} mx={mx} my={my} index={i} />
            ))}
          </div>
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
          >
            <DevelopCard />
          </motion.div>
        </div>
      </div>
    </section>
  )
}

function ReleaseBadge({ release }: { release: ReturnType<typeof useRelease> }) {
  if (release.state === 'ready')
    return (
      <a
        href={release.page}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-2 rounded-full border border-line bg-card/80 py-1 pr-3 pl-1 text-[13px] text-body shadow-card backdrop-blur transition-colors hover:border-line-strong"
      >
        <span className="rounded-full bg-accent px-2 py-0.5 text-[12px] font-medium text-white">New</span>
        Version {release.version} is out <ArrowRight className="size-3.5" />
      </a>
    )
  return (
    <a
      href={links.repo}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-2 rounded-full border border-line bg-card/80 px-3.5 py-1.5 text-[13px] text-body shadow-card backdrop-blur transition-colors hover:border-line-strong"
    >
      <span className="relative flex size-2">
        <span className="absolute inset-0 animate-ping rounded-full bg-amber-400/70" />
        <span className="relative size-2 rounded-full bg-amber-500" />
      </span>
      {release.state === 'none' ? 'First release coming soon' : 'Image Studio by AGS Labs'}
      <span className="text-faint">·</span>
      <span className="flex items-center gap-1.5 text-ink">
        <GitHubIcon className="size-3.5" /> Source on GitHub
      </span>
    </a>
  )
}

function Print({
  picture,
  className,
  rotate,
  depth,
  mx,
  my,
  index,
}: {
  picture: Picture
  className: string
  rotate: number
  depth: number
  mx: MotionValue<number>
  my: MotionValue<number>
  index: number
}) {
  const x = useTransform(mx, (v) => v * 40 * depth)
  const y = useTransform(my, (v) => v * 30 * depth)
  return (
    <motion.figure
      style={{ x, y, rotate }}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.8, delay: 0.5 + index * 0.08, ease: [0.22, 1, 0.36, 1] }}
      className={cn('absolute rounded-[6px] bg-white p-2 pb-7 shadow-float', className)}
    >
      <img
        src={`media/gallery-${picture.id}.webp`}
        alt=""
        className="aspect-square w-full rounded-[3px] object-cover"
        decoding="async"
      />
      <figcaption className="absolute right-2.5 bottom-2 left-2.5 truncate font-mono text-[10px] text-muted">
        {picture.model} · {picture.time}
      </figcaption>
    </motion.figure>
  )
}

/** A prompt types itself and the picture develops like a print in a tray. */
function DevelopCard() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.3 })
  const reduce = useReducedMotion()
  const [index, setIndex] = useState(0)
  // The page opens on a finished picture; the type-and-develop cycle starts with the next one.
  const first = useRef(true)
  const [typed, setTyped] = useState(reel[0].prompt.length)
  const [phase, setPhase] = useState<'typing' | 'developing' | 'done'>('done')
  const p = useMotionValue(1)
  const picture = reel[index]
  const total = steps[picture.model] ?? 30
  const [step, setStep] = useState(total)

  useEffect(() => p.on('change', (v) => setStep(Math.max(1, Math.round(v * total)))), [p, total])

  useEffect(() => {
    if (!inView) return
    if (reduce || first.current) {
      p.set(1)
      setTyped(picture.prompt.length)
      setPhase('done')
      const t = window.setTimeout(() => {
        first.current = false
        setIndex((i) => (i + 1) % reel.length)
      }, reduce ? 6000 : 3800)
      return () => window.clearTimeout(t)
    }
    let cancelled = false
    const timers: number[] = []
    p.set(0)
    setTyped(0)
    setPhase('typing')
    let n = 0
    const type = window.setInterval(() => {
      n += 2
      setTyped(Math.min(n, picture.prompt.length))
      if (n >= picture.prompt.length) {
        window.clearInterval(type)
        timers.push(
          window.setTimeout(() => {
            if (cancelled) return
            setPhase('developing')
            animate(p, 1, { duration: 2.8, ease: [0.45, 0, 0.2, 1] }).then(() => {
              if (cancelled) return
              setPhase('done')
              timers.push(window.setTimeout(() => setIndex((i) => (i + 1) % reel.length), 3600))
            })
          }, 350),
        )
      }
    }, 16)
    return () => {
      cancelled = true
      window.clearInterval(type)
      timers.forEach(window.clearTimeout)
      p.stop()
    }
  }, [index, inView, reduce, picture.prompt.length, p])

  const filter = useTransform(
    p,
    (v) =>
      `blur(${(1 - v) * 26}px) saturate(${0.15 + v * 0.85}) brightness(${1 + (1 - v) * 0.75}) contrast(${0.65 + v * 0.35})`,
  )
  const scale = useTransform(p, [0, 1], [1.08, 1])

  return (
    <div ref={ref} className="relative mx-auto max-w-[820px] rounded-[30px] border border-line bg-card/90 p-2.5 shadow-float backdrop-blur sm:p-3">
      <div className="rounded-[22px] bg-tint/80 px-4 pt-4 pb-3 sm:px-5">
        <div className="flex items-center gap-2 text-[12.5px] font-medium text-muted">
          <Sparkles className="size-3.5 text-accent" /> Prompt
        </div>
        <p className="mt-2 min-h-[3.2em] text-[15.5px] leading-[1.6] text-ink sm:min-h-[3.4em] sm:text-[17px]">
          {picture.prompt.slice(0, typed)}
          {phase === 'typing' && <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-pulse bg-accent" />}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-card px-3 text-[13px]">
            <Cpu className="size-3.5 text-muted" /> {picture.model} <ChevronDown className="size-3.5 text-faint" />
          </span>
          <span className="hidden h-8 items-center rounded-full border border-line bg-card px-3 text-[13px] text-body sm:inline-flex">
            On this PC
          </span>
          <span
            className={cn(
              'ml-auto inline-flex h-9 items-center gap-2 rounded-full px-4 text-[14px] font-medium text-white transition-colors',
              phase === 'developing' ? 'bg-accent/80' : 'bg-accent',
            )}
          >
            {phase === 'developing' ? (
              <span className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Generate
          </span>
        </div>
      </div>

      <div className="relative mt-2.5 aspect-[3/2] overflow-hidden rounded-[22px] bg-[#ece9e2] sm:mt-3">
        <motion.img
          key={picture.id}
          src={`media/gallery-${picture.id}.webp`}
          alt={picture.prompt}
          style={{ filter, scale }}
          className="absolute inset-0 h-full w-full object-cover"
          decoding="async"
        />
        <div className="absolute bottom-3 left-3 flex items-center gap-2 rounded-full bg-black/55 px-3 py-1.5 text-[12.5px] text-white backdrop-blur-md">
          {phase === 'done' ? (
            <>
              <Check className="size-3.5 text-emerald-300" /> Done in {picture.time}
              <span className="text-white/60">· laptop RTX 4060</span>
            </>
          ) : phase === 'developing' ? (
            <>
              <span className="relative h-1 w-16 overflow-hidden rounded-full bg-white/25">
                <span className="absolute inset-y-0 left-0 rounded-full bg-white" style={{ width: `${(step / total) * 100}%` }} />
              </span>
              Step {step} of {total}
            </>
          ) : (
            <span className="text-white/80">Waiting for the prompt…</span>
          )}
        </div>
        <div className="absolute right-3 bottom-3 flex gap-1.5">
          {reel.map((r, i) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setIndex(i)}
              aria-label={`Show example ${i + 1}`}
              className={cn('h-1.5 rounded-full transition-all', i === index ? 'w-5 bg-white' : 'w-1.5 bg-white/50 hover:bg-white/80')}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
