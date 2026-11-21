import { REPO as imageRepository } from './site'

export const glideRepository = 'https://github.com/gaffar273/GlideYT'
export const glideDownloads = {
  windows: glideRepository + '/releases/latest/download/GlideYT-Setup.exe',
  android: glideRepository + '/releases/latest/download/GlideYT-Android.apk',
}

export const products = [
  {
    slug: 'image-studio', name: 'Image Studio', platform: 'Windows desktop',
    description: 'Turn a prompt into a picture, then edit the details on your own PC.',
    repository: imageRepository,
  },
  {
    slug: 'glideYT', name: 'GlideYT', platform: 'Windows + Android',
    description: 'Search, play and pause YouTube on your laptop from your Android phone.',
    repository: glideRepository,
  },
] as const
