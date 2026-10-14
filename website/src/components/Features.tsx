import { forwardRef, useEffect, useRef, useState, type ReactNode } from 'react'
import { animate, motion, useInView, useMotionValue, useTransform } from 'motion/react'
import { Brush, Check, Cpu, Eye, Layers, Lock, MemoryStick, Workflow } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AnimatedBeam } from '@/components/ui/animated-beam'
import { Marquee } from '@/components/ui/marquee'
import { NumberTicker } from '@/components/ui/number-ticker'
import { AppIcon, Em, Intro } from './ui'
import { pipelineNames } from '@/content'
import { facts } from '@/site'

function Card({ className, visual, title, children }: { className?: string; visual: ReactNode; title: string; children: ReactNode }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className={cn('group flex flex-col overflow-hidden rounded-[28px] border border-line bg-card shadow-card', className)}
    >
      <div className="relative h-[230px] overflow-hidden bg-tint/70">{visual}</div>
      <div className="border-t border-line p-6 sm:p-7">
        <h3 className="text-[20px] font-semibold tracking-[-0.02em]">{title}</h3>
        <p className="mt-2 text-[15px] leading-relaxed text-body">{children}</p>
      </div>
    </motion.article>
  )
}

export function Features() {
  return (
    <section id="features" className="scroll-mt-24 px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <Workflow className="size-3.5 text-accent" /> What is inside
          </>
        }
        title={
          <>
            Built like a darkroom, <Em>not a slot machine.</Em>
          </>
        }
        lead="The model only chooses what to do. Coded pipelines do the work, on layers you can open, and the result is measured before you see it."
      />
      <div className="mx-auto mt-14 grid max-w-[1180px] gap-4 md:grid-cols-6">
        <Card className="md:col-span-4" visual={<GpuVisual />} title="Runs on your graphics card">
          RealVisXL, Z-Image Turbo, SDXL Turbo and FLUX.1 Kontext run on your NVIDIA card. When a game needs it, one
          button unloads every model and hands the memory back.
        </Card>
        <Card className="md:col-span-2" visual={<PipelinesVisual />} title="Procedures, not guesses">
          Every edit is a coded pipeline with exact commands. The language model only picks which ones to run.
        </Card>
        <Card className="md:col-span-2" visual={<LayersVisual />} title="Layers, never flattened">
          Each change lands on its own named layer in a real PSD. The original pixels are never overwritten.
        </Card>
        <Card className="md:col-span-4" visual={<ProvidersVisual />} title="Any model, your own keys">
          Use the bundled model, a local server like Ollama or LM Studio, or a cloud service with your own key. Keys are
          encrypted for your Windows account and only sent to their own service.
        </Card>
        <Card className="md:col-span-3" visual={<ChecksVisual />} title="Checks its own work">
          After an edit, each requirement is measured: aspect ratio, the exact text and where it sits, colour, and
          whether things got brighter or darker as asked.
        </Card>
        <Card className="md:col-span-3" visual={<AppsVisual />} title="Finish by hand in PhotoCraft or Krita">
          Open any picture in PhotoCraft with its layers, with all {facts.commands} of its commands at hand, or type edits
          onto Krita’s live canvas.
        </Card>
      </div>
    </section>
  )
}

/* ---- visuals ---- */

function Bar({ value, max, label, icon }: { value: ReturnType<typeof useMotionValue<number>>; max: number; label: string; icon: ReactNode }) {
  const width = useTransform(value, (v) => `${(v / max) * 100}%`)
  const text = useTransform(value, (v) => `${v.toFixed(1)} / ${max} GB`)
  return (
    <div>
      <div className="flex items-center justify-between text-[12.5px]">
        <span className="flex items-center gap-1.5 text-body">
          {icon} {label}
        </span>
        <motion.span className="font-mono text-muted">{text}</motion.span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-tint">
        <motion.div style={{ width }} className="h-full rounded-full bg-gradient-to-r from-accent to-[#60a5fa]" />
      </div>
    </div>
  )
}

function GpuVisual() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.5 })
  const gpu = useMotionValue(0.2)
  const ram = useMotionValue(6.1)
  const [state, setState] = useState<'loading' | 'busy' | 'freed'>('loading')

  useEffect(() => {
    if (!inView) return
    let live = true
    const loop = async () => {
      while (live) {
        setState('loading')
        await Promise.all([animate(gpu, 5.3, { duration: 1.8, ease: 'easeOut' }), animate(ram, 9.6, { duration: 1.8 })])
        if (!live) return
        setState('busy')
        await new Promise((r) => setTimeout(r, 2200))
        if (!live) return
        setState('freed')
        await Promise.all([animate(gpu, 0.2, { duration: 0.7 }), animate(ram, 6.1, { duration: 0.7 })])
        await new Promise((r) => setTimeout(r, 2200))
      }
    }
    loop()
    return () => {
      live = false
      gpu.stop()
      ram.stop()
    }
  }, [inView, gpu, ram])

  return (
    <div ref={ref} className="absolute inset-0 flex items-center justify-center p-6">
      <div className="w-full max-w-[420px] rounded-2xl border border-line bg-card p-4 shadow-card">
        <div className="flex items-center gap-2 text-[14px] font-semibold">
          <span className={cn('size-2 rounded-full', state === 'freed' ? 'bg-muted' : 'bg-ok')} />
          {state === 'freed' ? 'Models unloaded' : state === 'busy' ? 'Running FLUX.1 Kontext' : 'Loading the model'}
          <span
            className={cn(
              'ml-auto rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors',
              state === 'busy' ? 'border-accent bg-accent text-white' : 'border-line text-muted',
            )}
          >
            Free GPU memory
          </span>
        </div>
        <div className="mt-4 space-y-3">
          <Bar value={gpu} max={8} label="RTX 4060 Laptop" icon={<Cpu className="size-3.5" />} />
          <Bar value={ram} max={16} label="RAM" icon={<MemoryStick className="size-3.5" />} />
        </div>
        <div className="mt-4 flex items-center gap-1.5 text-[12px] text-muted">
          <Lock className="size-3" /> Pictures and prompts stay on this PC
        </div>
      </div>
    </div>
  )
}

function PipelinesVisual() {
  const half = Math.ceil(pipelineNames.length / 2)
  return (
    <div className="absolute inset-0">
      <div className="absolute top-5 left-6 z-10">
        <div className="text-[44px] leading-none font-semibold tracking-[-0.04em]">
          <NumberTicker value={facts.pipelines} className="tracking-[-0.04em] text-ink" />
        </div>
        <div className="mt-1 text-[12.5px] text-muted">pipelines to choose from</div>
      </div>
      <div className="absolute inset-x-0 bottom-5 flex flex-col gap-2 [mask-image:linear-gradient(to_right,transparent,black_15%,black_85%,transparent)]">
        <Marquee className="items-center p-0 [--duration:30s] [--gap:0.5rem]" repeat={2}>
          {pipelineNames.slice(0, half).map((n) => (
            <span key={n} className="h-fit shrink-0 rounded-full border border-line bg-card px-3 py-1 text-[12.5px] whitespace-nowrap text-body">
              {n}
            </span>
          ))}
        </Marquee>
        <Marquee reverse className="items-center p-0 [--duration:34s] [--gap:0.5rem]" repeat={2}>
          {pipelineNames.slice(half).map((n) => (
            <span key={n} className="h-fit shrink-0 rounded-full border border-line bg-card px-3 py-1 text-[12.5px] whitespace-nowrap text-body">
              {n}
            </span>
          ))}
        </Marquee>
        <Marquee className="items-center p-0 [--duration:38s] [--gap:0.5rem]" repeat={2}>
          {[...pipelineNames].reverse().slice(0, half).map((n) => (
            <span key={n} className="h-fit shrink-0 rounded-full border border-line bg-card px-3 py-1 text-[12.5px] whitespace-nowrap text-body">
              {n}
            </span>
          ))}
        </Marquee>
      </div>
    </div>
  )
}

function LayersVisual() {
  const layers = [
    { name: 'Best friends', kind: 'Type', tone: 'bg-white' },
    { name: 'Brighter dog', kind: 'Adjustment · mask', tone: 'bg-white' },
    { name: 'Cooler room', kind: 'Camera Raw · mask', tone: 'bg-white' },
    { name: 'Photo', kind: 'Original pixels', tone: 'bg-white' },
  ]
  return (
    <div className="absolute inset-0 flex items-center justify-center pt-16 [perspective:900px]">
      <div className="relative h-[120px] w-[180px] [transform-style:preserve-3d] [transform:rotateX(52deg)_rotateZ(-32deg)] transition-transform duration-700 group-hover:[transform:rotateX(46deg)_rotateZ(-26deg)]">
        {layers.map((l, i) => (
          <div
            key={l.name}
            style={{ transform: `translateZ(${(layers.length - 1 - i) * 30}px) translateY(${i * 6}px)` }}
            className={cn(
              'absolute inset-0 flex items-end rounded-xl border border-line-strong p-2.5 shadow-[0_10px_30px_-12px_rgb(0_0_0/0.25)] transition-transform duration-700',
              l.tone,
              i === layers.length - 1 && 'overflow-hidden',
            )}
          >
            {i === layers.length - 1 && (
              <img src="media/demo-plan-after.webp" alt="" className="absolute inset-0 h-full w-full rounded-xl object-cover opacity-90" />
            )}
            <span className="relative flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-[11px] font-medium shadow-sm">
              <Eye className="size-3 text-muted" /> {l.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

const Node = forwardRef<HTMLDivElement, { label: string; letter?: string; center?: boolean }>(function Node({ label, letter, center }, ref) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div
        ref={ref}
        className={cn(
          'z-10 grid place-items-center rounded-full border border-line bg-card font-semibold shadow-card',
          center ? 'size-16' : 'size-10 text-[13.5px] text-body',
        )}
      >
        {center ? <AppIcon className="size-11" /> : letter}
      </div>
      <span className="text-[11.5px] whitespace-nowrap text-muted">{label}</span>
    </div>
  )
})

function ProvidersVisual() {
  const box = useRef<HTMLDivElement>(null)
  const center = useRef<HTMLDivElement>(null)
  const l1 = useRef<HTMLDivElement>(null)
  const l2 = useRef<HTMLDivElement>(null)
  const l3 = useRef<HTMLDivElement>(null)
  const r1 = useRef<HTMLDivElement>(null)
  const r2 = useRef<HTMLDivElement>(null)
  const r3 = useRef<HTMLDivElement>(null)
  const beam = { gradientStartColor: '#2563eb', gradientStopColor: '#60a5fa', pathColor: '#a3a2a8', pathOpacity: 0.25 }
  return (
    <div ref={box} className="absolute inset-0 flex items-center justify-between px-8 sm:px-16">
      <div className="flex flex-col gap-2">
        <Node ref={l1} letter="Q" label="Bundled model" />
        <Node ref={l2} letter="O" label="Ollama" />
        <Node ref={l3} letter="L" label="LM Studio" />
      </div>
      <Node ref={center} center label="Image Studio" />
      <div className="flex flex-col gap-2">
        <Node ref={r1} letter="O" label="OpenAI" />
        <Node ref={r2} letter="G" label="Gemini" />
        <Node ref={r3} letter="A" label="Claude" />
      </div>
      {[l1, l2, l3].map((r, i) => (
        <AnimatedBeam key={`l${i}`} containerRef={box} fromRef={r} toRef={center} curvature={(i - 1) * -30} duration={4} delay={i * 0.4} {...beam} />
      ))}
      {[r1, r2, r3].map((r, i) => (
        <AnimatedBeam key={`r${i}`} containerRef={box} fromRef={r} toRef={center} curvature={(i - 1) * -30} reverse duration={4} delay={i * 0.4 + 0.2} {...beam} />
      ))}
    </div>
  )
}

function ChecksVisual() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.5 })
  const [done, setDone] = useState(0)
  // The measured checks from the real PhotoCraft run in Systematic.tsx, and its kept cat.
  const checks = ['Aspect ratio is 16:9 (1216 × 684)', 'Text reads exactly “Best friends”', 'Text sits at the top and fits', 'The cat was kept unchanged']
  useEffect(() => {
    if (!inView) return
    setDone(0)
    const timers = checks.map((_, i) => window.setTimeout(() => setDone(i + 1), 500 + i * 450))
    return () => timers.forEach(window.clearTimeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView])
  return (
    <div ref={ref} className="absolute inset-0 flex items-center justify-center p-6">
      <div className="w-full max-w-[340px] rounded-2xl border border-line bg-card p-4 shadow-card">
        <div className="flex items-center justify-between text-[13px] font-semibold">
          Result check
          <span className={cn('text-[12px] font-medium transition-colors', done === checks.length ? 'text-ok' : 'text-muted')}>
            {done === checks.length ? 'Everything checked out' : `Measuring ${done}/${checks.length}`}
          </span>
        </div>
        <ul className="mt-3 space-y-2">
          {checks.map((c, i) => (
            <li key={c} className="flex items-center gap-2.5 text-[13px]">
              <span
                className={cn(
                  'grid size-[18px] place-items-center rounded-full border transition-all duration-300',
                  i < done ? 'border-ok bg-ok text-white' : 'border-line-strong text-transparent',
                )}
              >
                <Check className="size-3" strokeWidth={3} />
              </span>
              <span className={cn('transition-colors duration-300', i < done ? 'text-ink' : 'text-faint')}>{c}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function AppsVisual() {
  return (
    <div className="absolute inset-0 flex items-center justify-center gap-5">
      <motion.div whileHover={{ y: -4, rotate: -2 }} className="flex w-[150px] flex-col items-center gap-3 rounded-2xl border border-line bg-card p-5 shadow-card">
        <span className="grid size-14 place-items-center rounded-2xl bg-[#1f2937] text-white">
          <Layers className="size-7" />
        </span>
        <span className="text-center">
          <span className="block text-[14px] font-semibold">PhotoCraft</span>
          <span className="block text-[12px] text-muted">{facts.commands} commands</span>
        </span>
      </motion.div>
      <motion.div whileHover={{ y: -4, rotate: 2 }} className="flex w-[150px] flex-col items-center gap-3 rounded-2xl border border-line bg-card p-5 shadow-card">
        <span className="grid size-14 place-items-center rounded-2xl bg-[#3b2a6b] text-white">
          <Brush className="size-7" />
        </span>
        <span className="text-center">
          <span className="block text-[14px] font-semibold">Krita</span>
          <span className="block text-[12px] text-muted">Live canvas</span>
        </span>
      </motion.div>
    </div>
  )
}
