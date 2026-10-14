import { Marquee } from '@/components/ui/marquee'
import { apps, models, providers } from '@/content'

const names = [...models, ...apps, ...providers]

export function WorksWith() {
  return (
    <section aria-label="Models and apps it works with" className="pb-8">
      <p className="text-center text-[13.5px] text-muted">Runs the models and apps you choose</p>
      <div className="relative mt-4 [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
        <Marquee pauseOnHover className="[--duration:48s] [--gap:2.75rem]">
          {names.map((n) => (
            <span key={n} className="flex items-center gap-[2.75rem] text-[19px] font-semibold tracking-[-0.02em] whitespace-nowrap text-ink/45">
              {n}
              <span className="size-1 rounded-full bg-ink/20" />
            </span>
          ))}
        </Marquee>
      </div>
    </section>
  )
}
