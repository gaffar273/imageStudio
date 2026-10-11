import {
  ChevronDown,
  Dices,
  ScanLine,
  Settings2,
  Sparkles,
  Upload,
  WandSparkles,
  X,
  Zap,
} from 'lucide-react';
import type { Config, Settings } from '../lib/types';
import { Range, SectionLabel, Toggle } from './Controls';
import { readImage } from '../lib/api';
export const ideas = [
  {
    label: 'Coastal escape',
    prompt:
      'A quiet Mediterranean seaside town on steep cliffs, terracotta rooftops, turquoise water and a winding coastal road, photographed in soft late afternoon light.',
  },
  {
    label: 'A little cinematic',
    prompt:
      'A solitary traveler at a rainy Tokyo street corner at night, glowing neon reflected in puddles, candid 35mm street photograph.',
  },
  {
    label: 'Everyday beauty',
    prompt:
      'Morning sunlight falling across a ceramic coffee cup and a half-read book on a wooden table, a small vase of wildflowers, natural intimate photograph.',
  },
];
interface Props {
  config: Config;
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  busy: boolean;
  generate: () => void;
  sketch: () => void;
  error: (message: string) => void;
}
export function PromptPanel({ config, settings: s, update, busy, generate, sketch, error }: Props) {
  const model = config.models.find((model) => model.id === s.model);
  return (
    <section className="prompt-panel">
      <div className="panel-heading">
        <span>
          <WandSparkles size={17} />
          Your vision
        </span>
        <span className="small-badge">TEXT TO IMAGE</span>
      </div>
      <div className="panel-scroll">
        <SectionLabel
          extra={
            <button
              className="text-button"
              onClick={() => update({ prompt: ideas[Math.floor(Math.random() * ideas.length)].prompt })}
            >
              <Dices size={13} />
              Surprise me
            </button>
          }
        >
          Prompt
        </SectionLabel>
        <div className="prompt-field">
          <textarea
            aria-label="Image prompt"
            placeholder="A place you've never been. A moment you've imagined. Describe it here…"
            value={s.prompt}
            maxLength={6000}
            onChange={(e) => update({ prompt: e.target.value })}
          />
          <div>
            <span>Let your imagination do the talking.</span>
            <span>{s.prompt.length}/6000</span>
          </div>
        </div>
        <div className="inspiration-chips">
          {ideas.map((idea) => (
            <button key={idea.label} onClick={() => update({ prompt: idea.prompt })}>
              {idea.label}
              <span>↗</span>
            </button>
          ))}
        </div>
        <Toggle
          label="Smart prompt"
          description={
            config.assistant ? 'A little help shaping your idea' : 'Download the prompt assistant to enable'
          }
          checked={s.smart}
          disabled={!config.assistant}
          onChange={(smart) => update({ smart })}
        />
        <div className="divider" />
        <SectionLabel>Model</SectionLabel>
        <div className="model-picker">
          <span className="model-icon">
            <Sparkles size={19} />
          </span>
          <label>
            <span className="sr-only">Generation model</span>
            <select
              value={s.model}
              onChange={(e) =>
                update({
                  model: e.target.value,
                  steps: { realistic: 30, accurate: 9, turbo: 4 }[e.target.value],
                  detail: 'Off',
                })
              }
            >
              {config.models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.id === 'realistic'
                    ? 'RealVisXL 5.0'
                    : model.id === 'accurate'
                      ? 'Z-Image Turbo'
                      : 'SDXL Turbo'}
                  {!model.ready ? ' · Not installed' : ''}
                </option>
              ))}
            </select>
            <small>
              {s.model === 'realistic'
                ? 'Lifelike people, beautiful details'
                : s.model === 'accurate'
                  ? 'Precise prompts, thoughtful compositions'
                  : 'Fast ideas, endless possibilities'}
            </small>
          </label>
          <ChevronDown size={15} />
        </div>
        <SectionLabel extra={<span className="muted">Aspect ratio</span>}>Image format</SectionLabel>
        <div className="aspect-options">
          {config.sizes.slice(0, 4).map((size, index) => (
            <button
              key={size.id}
              className={s.size === size.id ? 'selected' : ''}
              onClick={() => update({ size: size.id })}
            >
              <span className={`aspect-shape shape-${index}`} />
              <span>{['1:1', '2:3', '3:2', '16:9'][index]}</span>
            </button>
          ))}
        </div>
        <label className="dimension-select">
          <span className="sr-only">Image dimensions</span>
          <select value={s.size} onChange={(e) => update({ size: e.target.value })}>
            {config.sizes.map((size) => (
              <option key={size.id}>{size.id}</option>
            ))}
          </select>
        </label>
        <SectionLabel>Photo style</SectionLabel>
        <div className="segmented">
          {['Natural photo', 'Polished'].map((style) => (
            <button
              key={style}
              className={s.photo_style === style ? 'selected' : ''}
              onClick={() => update({ photo_style: style })}
            >
              {style === 'Natural photo' ? '◉  Natural' : '✧  Polished'}
            </button>
          ))}
        </div>
        <div className="count-row">
          <span>Number of images</span>
          <div className="count-options">
            {[1, 2, 3, 4].map((count) => (
              <button
                key={count}
                className={s.count === count ? 'selected' : ''}
                onClick={() => update({ count })}
              >
                {count}
              </button>
            ))}
          </div>
        </div>
        <details className="advanced">
          <summary>
            <Settings2 size={15} />
            Fine-tune your image
            <ChevronDown size={14} />
          </summary>
          <div className="advanced-body">
            <Range
              label="Rendering steps"
              value={s.steps}
              min={s.model === 'accurate' ? 6 : s.model === 'turbo' ? 4 : 20}
              max={s.model === 'accurate' ? 16 : s.model === 'turbo' ? 4 : 50}
              onChange={(steps) => update({ steps })}
              disabled={s.model === 'turbo'}
            />
            {s.model === 'realistic' && (
              <Range
                label="Prompt strength"
                value={s.guidance}
                min={1}
                max={12}
                step={0.5}
                onChange={(guidance) => update({ guidance })}
              />
            )}
            <label className="field-label">
              Seed
              <div className="seed-field">
                <input
                  aria-label="Seed"
                  value={s.seed}
                  placeholder="Random"
                  inputMode="numeric"
                  onChange={(e) => update({ seed: e.target.value.replace(/\D/g, '') })}
                />
                <button
                  className="icon-button"
                  title="Randomize seed"
                  onClick={() => update({ seed: String(Math.floor(Math.random() * 2147483647)) })}
                >
                  <Dices size={15} />
                </button>
              </div>
            </label>
            <label className="field-label">
              Things to avoid
              <textarea
                aria-label="Negative prompt"
                rows={3}
                value={s.negative_prompt}
                onChange={(e) => update({ negative_prompt: e.target.value })}
              />
            </label>
            <label className="field-label">
              High-detail pass
              <select value={s.detail} onChange={(e) => update({ detail: e.target.value })}>
                <option>Off</option>
                <option>1.5× size</option>
                <option>2× size</option>
              </select>
            </label>
            {s.detail !== 'Off' && (
              <Range
                label="Detail strength"
                value={s.detail_strength}
                min={0.1}
                max={0.7}
                step={0.05}
                onChange={(detail_strength) => update({ detail_strength })}
              />
            )}
            <label className="field-label">
              Photo finish
              <select value={s.photo_finish} onChange={(e) => update({ photo_finish: e.target.value })}>
                <option>Off</option>
                <option>Light</option>
                <option>Film</option>
              </select>
            </label>
            <Toggle label="Vary faces" checked={s.vary} onChange={(vary) => update({ vary })} />
            <Toggle
              label="Face & hand repair"
              checked={s.repair}
              disabled={!config.repair}
              onChange={(repair) => update({ repair })}
            />
            {s.repair && (
              <Range
                label="Repair strength"
                value={s.repair_strength}
                min={0.1}
                max={0.7}
                step={0.05}
                onChange={(repair_strength) => update({ repair_strength })}
              />
            )}
            <Toggle
              label="Reference faces"
              checked={s.references}
              disabled={!config.references}
              onChange={(references) => update({ references })}
            />
            <Toggle
              label="Check & retry"
              checked={s.check}
              disabled={!config.assistant}
              onChange={(check) => update({ check })}
            />
            {s.check && (
              <Range
                label="Maximum attempts"
                min={1}
                max={4}
                value={s.attempts}
                onChange={(attempts) => update({ attempts })}
              />
            )}
            {s.model === 'accurate' && (
              <Toggle
                label="Finish with RealVisXL"
                checked={s.combine}
                onChange={(combine) => update({ combine })}
              />
            )}
            {config.lora && (
              <Range
                label="Realism LoRA"
                value={s.realism}
                min={0}
                max={1}
                step={0.05}
                onChange={(realism) => update({ realism })}
              />
            )}
            {config.personal_lora && (
              <Range
                label="My style (learned from favorites)"
                value={s.personal}
                min={0}
                max={1}
                step={0.05}
                onChange={(personal) => update({ personal })}
              />
            )}
          </div>
        </details>
        {s.model !== 'turbo' && (
          <details className="advanced">
            <summary>
              <ScanLine size={15} />
              Guide with a sketch
              <ChevronDown size={14} />
            </summary>
            <div className="advanced-body">
              <p className="muted">Use shapes and colors to guide the composition.</p>
              {s.sketch && (
                <div className="sketch-preview">
                  <img src={s.sketch} alt="Composition sketch" />
                  <button
                    className="icon-button"
                    aria-label="Remove sketch"
                    onClick={() => update({ sketch: null })}
                  >
                    <X size={16} />
                  </button>
                </div>
              )}
              <label className="button upload-button">
                <Upload size={14} />
                Upload sketch
                <input
                  type="file"
                  accept="image/*"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      try {
                        update({ sketch: await readImage(file) });
                      } catch (err) {
                        error(String(err));
                      }
                  }}
                />
              </label>
              <button
                className="button"
                disabled={!config.assistant || busy || !s.prompt.trim()}
                onClick={sketch}
              >
                <WandSparkles size={14} />
                Sketch from prompt
              </button>
              <Range
                label="Freedom from sketch"
                value={s.sketch_freedom}
                min={0.1}
                max={1}
                step={0.05}
                onChange={(sketch_freedom) => update({ sketch_freedom })}
              />
            </div>
          </details>
        )}
      </div>
      <div className="generate-footer">
        <button
          className="generate-button"
          disabled={busy || !s.prompt.trim() || !model?.ready}
          onClick={generate}
        >
          <Sparkles size={18} />
          {busy ? 'Creating your image…' : 'Generate image'}
          <span>↵</span>
        </button>
        <p>
          <Zap size={12} />
          {!model?.ready ? 'Install this model from scripts/windows' : 'Ctrl + Enter to generate'}
        </p>
      </div>
    </section>
  );
}
