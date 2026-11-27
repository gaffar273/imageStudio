import catalog from '../public/product-catalog.json'

export const products = catalog
export const glideRepository = 'https://github.com/gaffar273/GlideYT'
export const glideDownloads = {
  windows: '/downloads/glideyt/2c0d85b9da9d/GlideYT-Setup.exe',
  android: glideRepository + '/releases/latest/download/GlideYT-Android.apk',
}

export const rillboardRepository = 'https://github.com/gaffar273/Rillboard'
export const rillboardVersion = '2.1.0'
const rillboardDownloadDirectory = '/downloads/rillboard/' + rillboardVersion
export const rillboardDownloads = {
  deb: rillboardDownloadDirectory + '/rillboard.deb?build=keyboard-fix',
  portable: rillboardDownloadDirectory + '/rillboard-linux.tar.gz?build=keyboard-fix',
  installer: rillboardDownloadDirectory + '/Rillboard-Windows.zip?build=keyboard-fix',
  standalone: rillboardDownloadDirectory + '/Rillboard.exe?build=keyboard-fix',
}
