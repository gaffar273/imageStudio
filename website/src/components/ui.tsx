import { Aperture, Minus, Square, X } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { BlurFade } from '@/components/ui/blur-fade'

type ButtonProps = ComponentProps<'a'> & {
  variant?: 'primary' | 'dark' | 'outline' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
}

export function Button({ variant = 'outline', size = 'md', className, children, ...props }: ButtonProps) {
  return (
    <a
      className={cn(
        'group/btn inline-flex items-center justify-center gap-2 rounded-full font-medium whitespace-nowrap transition-all duration-200 select-none active:scale-[0.98]',
        size === 'sm' && 'h-9 px-4 text-[14px]',
        size === 'md' && 'h-11 px-5 text-[15px]',
        size === 'lg' && 'h-[52px] px-7 text-[16px]',
        variant === 'primary' &&
          'bg-accent text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_8px_20px_-8px_rgb(37_99_235/0.7)] hover:bg-accent-ink',
        variant === 'dark' && 'bg-ink text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.15)] hover:bg-[#2b2b30]',
        variant === 'outline' && 'border border-line-strong bg-card text-ink shadow-card hover:border-ink/40',
        variant === 'ghost' && 'text-body hover:bg-tint hover:text-ink',
        className,
      )}
      {...props}
    >
      {children}
    </a>
  )
}

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full border border-line bg-card/80 px-3.5 py-1.5 text-[13px] text-body shadow-card backdrop-blur',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Small pill, big heading with a serif accent, short lead. Every section opens with one. */
export function Intro({
  badge,
  title,
  lead,
  align = 'center',
  className,
}: {
  badge: ReactNode
  title: ReactNode
  lead?: ReactNode
  align?: 'center' | 'left'
  className?: string
}) {
  return (
    <BlurFade inView className={cn(align === 'center' ? 'mx-auto max-w-3xl text-center' : 'max-w-2xl', className)}>
      <Pill>{badge}</Pill>
      <h2 className="mt-5 text-[40px] leading-[1.02] font-semibold tracking-[-0.04em] sm:text-[56px]">{title}</h2>
      {lead && (
        <p className={cn('mt-5 text-[17px] leading-relaxed text-body', align === 'center' && 'mx-auto max-w-[58ch]')}>
          {lead}
        </p>
      )}
    </BlurFade>
  )
}

export function Em({ children }: { children: ReactNode }) {
  return <span className="serif pr-[0.04em] text-[1.08em] leading-[0.9]">{children}</span>
}

export function AppIcon({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'grid shrink-0 place-items-center rounded-[26%] bg-gradient-to-b from-[#3d84f7] to-[#1d4ed8] text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.35),0_10px_24px_-10px_rgb(37_99_235/0.7)]',
        className,
      )}
    >
      <Aperture className="size-[58%]" strokeWidth={1.9} />
    </span>
  )
}

export function Logo({ org }: { org?: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <AppIcon className="size-8" />
      <span className="leading-none">
        <span className="block text-[15px] font-semibold tracking-[-0.01em]">Image Studio</span>
        {org && <span className="mt-1 block text-[11.5px] text-muted">by {org}</span>}
      </span>
    </span>
  )
}

/** A Windows 11 style window around an app screenshot. */
export function AppWindow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-hidden rounded-[14px] border border-line-strong/80 bg-card shadow-float', className)}>
      <div className="flex h-9 items-center border-b border-line bg-[#fbfbfa] pl-3.5 text-[12.5px] text-muted">
        <span className="flex items-center gap-2">
          <AppIcon className="size-4 rounded-[5px] shadow-none" />
          Image Studio
        </span>
        <span className="ml-auto flex h-full">
          <span className="grid w-11 place-items-center"><Minus className="size-3.5" /></span>
          <span className="grid w-11 place-items-center"><Square className="size-3" /></span>
          <span className="grid w-11 place-items-center"><X className="size-3.5" /></span>
        </span>
      </div>
      {children}
    </div>
  )
}

export function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="currentColor">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  )
}

export function WindowsIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="currentColor">
      <path d="M3 5.1 10.4 4v7.1H3V5.1Zm8.3-1.2L21 2.5v8.6h-9.7V3.9ZM3 12.9h7.4V20L3 18.9v-6Zm8.3 0H21v8.6l-9.7-1.4v-7.2Z" />
    </svg>
  )
}
