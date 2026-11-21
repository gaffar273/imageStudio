import { createElement } from 'react'
import { ArrowDownToLine, Eye } from 'lucide-react'
import { Button, GitHubIcon } from './ui'
import { links } from '@/site'
import { useRelease, windowsDownload } from '@/hooks/useRelease'

export function Footer() {
  const windows = windowsDownload(useRelease())
  return createElement('ags-footer', { variant: 'image' }, <>
    {windows ? <Button slot="actions" variant="primary" size="lg" href={windows.url}>
      <ArrowDownToLine size={18}/> Download for Windows
    </Button> : <Button slot="actions" size="lg" href={links.watch}><Eye size={18}/> Watch for the release</Button>}
    <Button slot="actions" size="lg" href={links.repo} className="border-white/20 bg-white/5 text-white"><GitHubIcon className="size-4"/> View the code</Button>
  </>)
}
