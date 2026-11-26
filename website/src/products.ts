import catalog from '../public/product-catalog.json'

export const products = catalog
export const glideRepository = 'https://github.com/gaffar273/GlideYT'
export const glideDownloads = {
  windows: '/downloads/glideyt/2c0d85b9da9d/GlideYT-Setup.exe',
  android: glideRepository + '/releases/latest/download/GlideYT-Android.apk',
}

export const rillboardRepository = 'https://github.com/gaffar273/Rillboard'
export const rillboardDownloads = {
  installer: rillboardRepository + '/releases/latest/download/Rillboard-Windows.zip',
  standalone: rillboardRepository + '/releases/latest/download/Rillboard.exe',
}
