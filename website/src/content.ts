// Real pictures from the Image Studio library: the prompt that made each one, the model and the
// time it took on a laptop RTX 4060 (8 GB), copied from each picture's saved metadata.

export type Picture = { id: string; w: number; h: number; model: string; time: string; prompt: string }

export const pictures: Picture[] = [
  { id: 'seaside', w: 1536, h: 1024, model: 'RealVisXL 5.0', time: '67 s', prompt: 'A wide cinematic photograph of a seaside town built on steep cliffs above the Mediterranean, terracotta rooftops, fishing boats in the harbor, golden evening light' },
  { id: 'umbrella', w: 1536, h: 1024, model: 'RealVisXL 5.0', time: '72 s', prompt: 'Candid street portrait of a woman under a transparent umbrella in a rainy neon-lit Tokyo alleyway, neon blue and magenta reflections on wet asphalt, shot on 35mm film' },
  { id: 'shelter', w: 1536, h: 1024, model: 'RealVisXL 5.0', time: '58 s', prompt: 'Candid street photo of a lone commuter waiting under a dimly lit bus shelter at night. Raindrops running down scratched Plexiglas, reflections of distant red taillights on wet pavement' },
  { id: 'baking', w: 1216, h: 832, model: 'RealVisXL 5.0', time: '1 min 58 s', prompt: 'A wide photograph of a grandmother and her two grandsons baking cookies in a sunny kitchen, all three smiling, flour on their hands' },
  { id: 'sign', w: 1024, h: 1024, model: 'Z-Image Turbo', time: '63 s', prompt: 'A photograph of a wooden sign hanging on a cafe door that says "Local Image Studio" in white painted letters, morning light.' },
  { id: 'fisherman', w: 832, h: 1216, model: 'Z-Image Turbo', time: '2 min 30 s', prompt: 'Close-up portrait photograph of an elderly Indian fisherman with a salt-and-pepper beard, wearing a faded blue cotton shirt, holding a fishing net, beside the sea at sunrise' },
  { id: 'chef', w: 1024, h: 1024, model: 'RealVisXL 5.0', time: '75 s', prompt: 'A documentary photograph of a 40-year-old male chef in a white apron standing in a rustic restaurant kitchen, warm practical lighting, natural skin texture' },
  { id: 'fox', w: 512, h: 512, model: 'SDXL Turbo', time: '20 s', prompt: 'A red fox in a snowy pine forest, wildlife photograph, soft morning light' },
  { id: 'lake', w: 512, h: 512, model: 'SDXL Turbo', time: '20 s', prompt: 'A quiet alpine lake with snowy mountains and pine trees at sunrise, natural landscape photograph' },
  { id: 'lighthouse', w: 512, h: 512, model: 'SDXL Turbo', time: '16 s', prompt: 'A red lighthouse on a rocky shore at sunset, photograph' },
]

export const byId = (id: string) => pictures.find((p) => p.id === id)!

export const pipelineNames = [
  'Marketplace product photo', 'Full portrait retouch', 'Studio headshot', 'Real estate interior', 'Sunset enhancement',
  'Food photo', 'Bright and airy wedding edit', 'Fine-art black and white', 'Scanned photo restoration',
  'YouTube thumbnail', 'Instagram-ready post', 'Prepare for print', 'Make the subject stand out', 'Color splash',
  'Cinematic film still', 'Instant photo', 'Miniature (toy town)', 'Pet portrait', 'Fix a backlit subject',
  'Graduated filter', 'Recover bright windows', 'Relight', 'Split toning', 'Change the season’s colors',
  'Remove an object', 'Restore an old photo', 'Blur the background', 'Cut out the subject', 'Contact shadow',
  'Tilt-shift miniature', 'Glow (Orton)', 'Light leak', 'Straighten the horizon', 'Upright perspective',
  'Passport or ID photo', 'Recompose by a composition rule', 'Add text', 'Cinema letterbox bars', 'Paint new content with AI',
]

export const models = ['RealVisXL 5.0', 'Z-Image Turbo', 'SDXL Turbo', 'FLUX.1 Kontext', 'SAM 2.1', 'Qwen3-VL']
export const providers = ['OpenAI', 'Google Gemini', 'fal.ai', 'Replicate', 'Anthropic Claude', 'OpenRouter', 'Ollama', 'LM Studio']
export const apps = ['PhotoCraft', 'Krita']
