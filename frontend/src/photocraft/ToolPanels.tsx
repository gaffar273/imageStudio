import { useMemo, useState } from 'react';
import { FlipHorizontal2, FlipVertical2, Play, RotateCcw, RotateCw, Search, Wand2 } from 'lucide-react';
import { FieldForm } from './FieldForm';
import type { Actions, Command, Edit } from './types';
import { flatten } from './types';

/* ---------- small shared controls ---------- */

const TARGETS = [
  ['whole image', 'Whole image'],
  ['main subject', 'Subject'],
  ['background', 'Background'],
  ['sky', 'Sky'],
] as const;

function Targets({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="pc-segmented" role="radiogroup" aria-label="Apply to">
      {TARGETS.map(([id, label]) => (
        <button
          key={id}
          role="radio"
          aria-checked={value === id}
          className={value === id ? 'on' : ''}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Strength({ value, onChange }: { value: string; onChange: (value: Edit['strength']) => void }) {
  return (
    <div className="pc-segmented small" role="radiogroup" aria-label="Strength">
      {(['subtle', 'moderate', 'strong'] as const).map((id) => (
        <button
          key={id}
          role="radio"
          aria-checked={value === id}
          className={value === id ? 'on' : ''}
          onClick={() => onChange(id)}
        >
          {id[0].toUpperCase() + id.slice(1)}
        </button>
      ))}
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  format = (v: number) => (v > 0 ? `+${v}` : `${v}`),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
}) {
  return (
    <label
      className={`pc-slider ${value ? 'changed' : ''}`}
      onDoubleClick={() => onChange(0)}
      title="Double-click to reset"
    >
      <span>
        {label}
        <output>{format(value)}</output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="pc-section">
      <span className="eyebrow">{title}</span>
      {children}
    </section>
  );
}

const POSITIONS = [
  'top left',
  'top',
  'top right',
  'left',
  'center',
  'right',
  'bottom left',
  'bottom',
  'bottom right',
];

function PositionGrid({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="pc-position" role="radiogroup" aria-label="Position">
      {POSITIONS.map((position) => (
        <button
          key={position}
          role="radio"
          aria-checked={value === position}
          aria-label={position}
          title={position}
          className={value === position ? 'on' : ''}
          onClick={() => onChange(position)}
        >
          <span />
        </button>
      ))}
    </div>
  );
}

/* ---------- Adjust ---------- */

const ADJUSTMENTS: { group: string; items: [string, string, number, number, number?][] }[] = [
  {
    group: 'LIGHT',
    items: [
      ['exposure', 'Exposure (EV)', -3, 3, 0.05],
      ['brightness', 'Brightness', -100, 100],
      ['contrast', 'Contrast', -50, 100],
      ['highlights', 'Highlights', -100, 100],
      ['shadows', 'Shadows', -100, 100],
      ['whites', 'Whites', -100, 100],
      ['blacks', 'Blacks', -100, 100],
    ],
  },
  {
    group: 'COLOR',
    items: [
      ['temperature', 'Temperature', -100, 100],
      ['tint', 'Tint', -100, 100],
      ['vibrance', 'Vibrance', -100, 100],
      ['saturation', 'Saturation', -100, 100],
      ['hue_shift', 'Hue', -180, 180],
    ],
  },
  {
    group: 'PRESENCE',
    items: [
      ['texture', 'Texture', -100, 100],
      ['clarity', 'Clarity', -100, 100],
      ['dehaze', 'Dehaze', -100, 100],
    ],
  },
  {
    group: 'DETAIL & EFFECTS',
    items: [
      ['sharpen', 'Sharpening', 0, 150],
      ['noise_reduction', 'Noise reduction', 0, 100],
      ['grain', 'Grain', 0, 100],
      ['vignette', 'Vignette', -100, 100],
    ],
  },
];

export function AdjustPanel({ document, busy, edits }: Actions) {
  const [values, setValues] = useState<Record<string, number>>({});
  const [target, setTarget] = useState('whole image');
  const changed = Object.entries(values).filter(([, value]) => value !== 0);
  function apply() {
    edits(
      changed.map(([action, value]) => ({
        action,
        value: Math.abs(value),
        direction: value > 0 ? 'increase' : 'decrease',
        target,
        quote: action === 'vignette' && value > 0 ? 'lighten the edges' : `${action} ${value}`,
      })),
      `Adjust: ${changed.map(([action, value]) => `${action.replace('_', ' ')} ${value > 0 ? '+' : ''}${value}`).join(', ')}`,
    );
    setValues({});
  }
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Adjust</h2>
        <p>Light, color and detail, developed non-destructively. Choose where it applies.</p>
      </div>
      <Targets value={target} onChange={setTarget} />
      {ADJUSTMENTS.map(({ group, items }) => (
        <Section key={group} title={group}>
          {items.map(([action, label, min, max, step]) => (
            <Slider
              key={action}
              label={label}
              min={min}
              max={max}
              step={step}
              value={values[action] || 0}
              onChange={(value) => setValues({ ...values, [action]: value })}
            />
          ))}
        </Section>
      ))}
      <div className="pc-sticky-actions">
        <button className="button" disabled={!changed.length} onClick={() => setValues({})}>
          Reset
        </button>
        <button className="generate-button" disabled={!document || busy || !changed.length} onClick={apply}>
          Apply {changed.length || ''} adjustment{changed.length === 1 ? '' : 's'}
        </button>
      </div>
    </div>
  );
}

/* ---------- Looks ---------- */

const LOOKS: [string, string, string][] = [
  ['professional polish', 'Professional polish', 'linear-gradient(135deg,#6b8f71,#d9c9a3)'],
  ['warm portrait', 'Warm portrait', 'linear-gradient(135deg,#a8643a,#f2c38b)'],
  ['cinematic', 'Cinematic', 'linear-gradient(135deg,#1d5c63,#e0894a)'],
  ['moody', 'Moody', 'linear-gradient(135deg,#1c2229,#5c6670)'],
  ['dramatic', 'Dramatic', 'linear-gradient(135deg,#111,#8a8f99)'],
  ['bright and airy', 'Bright & airy', 'linear-gradient(135deg,#dfe8ee,#fff6e8)'],
  ['vintage', 'Vintage film', 'linear-gradient(135deg,#8c7a5b,#d8c7a0)'],
  ['matte', 'Matte', 'linear-gradient(135deg,#4c4c4c,#bdb7aa)'],
  ['hdr', 'HDR detail', 'linear-gradient(135deg,#25476a,#e6b54a)'],
  ['bleachBypass', 'Bleach bypass', 'linear-gradient(135deg,#5a5f5c,#c9cbc4)'],
  ['crossProcess', 'Cross process', 'linear-gradient(135deg,#2f7a5f,#e8d35a)'],
  ['dayForNight', 'Day for night', 'linear-gradient(135deg,#0f1f3d,#3d5a8a)'],
  ['warm', 'Warm', 'linear-gradient(135deg,#b56b2a,#f5c27a)'],
  ['cool', 'Cool', 'linear-gradient(135deg,#2a5fb5,#9cc7f5)'],
  ['monoContrast', 'Noir', 'linear-gradient(135deg,#000,#ddd)'],
];

export function LooksPanel({ document, busy, edits }: Actions) {
  const [strength, setStrength] = useState<Edit['strength']>('moderate');
  const [tint, setTint] = useState('#a3845c');
  const [dark, setDark] = useState('#14213d');
  const [light, setLight] = useState('#fcd116');
  const disabled = !document || busy;
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Looks</h2>
        <p>Complete color grades. Each one is a set of editable layers and filters.</p>
      </div>
      <Strength value={strength || 'moderate'} onChange={setStrength} />
      <div className="pc-looks">
        {LOOKS.map(([id, label, swatch]) => (
          <button
            key={id}
            disabled={disabled}
            onClick={() => edits([{ action: 'look', choice: id, quote: label, strength }], `Look: ${label}`)}
          >
            <span style={{ background: swatch }} />
            {label}
          </button>
        ))}
      </div>
      <Section title="BLACK & WHITE">
        <div className="pc-button-row">
          {['neutral', 'high contrast', 'infrared'].map((style) => (
            <button
              key={style}
              className="button"
              disabled={disabled}
              onClick={() =>
                edits(
                  [{ action: 'black_and_white', choice: style, quote: `black and white ${style}` }],
                  `Black & white (${style})`,
                )
              }
            >
              {style[0].toUpperCase() + style.slice(1)}
            </button>
          ))}
        </div>
        <div className="pc-inline">
          <label className="pc-color">
            Toned
            <input type="color" value={tint} onChange={(event) => setTint(event.target.value)} />
          </label>
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits(
                [{ action: 'black_and_white', color: tint, quote: 'toned black and white' }],
                'Toned black & white',
              )
            }
          >
            Apply toned
          </button>
          <button
            className="button"
            disabled={disabled}
            onClick={() => edits([{ action: 'sepia', quote: 'sepia' }], 'Sepia')}
          >
            Sepia
          </button>
        </div>
      </Section>
      <Section title="DUOTONE">
        <div className="pc-inline">
          <label className="pc-color">
            Shadows
            <input type="color" value={dark} onChange={(event) => setDark(event.target.value)} />
          </label>
          <label className="pc-color">
            Highlights
            <input type="color" value={light} onChange={(event) => setLight(event.target.value)} />
          </label>
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits([{ action: 'duotone', color: `${dark} and ${light}`, quote: 'duotone' }], 'Duotone')
            }
          >
            Apply
          </button>
        </div>
      </Section>
    </div>
  );
}

/* ---------- Crop & rotate ---------- */

const ASPECTS = ['1:1', '4:5', '5:4', '3:2', '2:3', '16:9', '9:16', '3:1'];

export function CropPanel({ document, busy, edits }: Actions) {
  const [keep, setKeep] = useState('center');
  const [object, setObject] = useState('');
  const [angle, setAngle] = useState(0);
  const [border, setBorder] = useState(40);
  const [borderColor, setBorderColor] = useState('#ffffff');
  const width = document?.state.width || 0;
  const height = document?.state.height || 0;
  const [size, setSize] = useState({ w: '', h: '' });
  const [lock, setLock] = useState(true);
  const disabled = !document || busy;

  function crop(aspect: string) {
    const target =
      keep === 'subject' ? 'main subject' : keep === 'object' && object.trim() ? 'object' : 'whole image';
    edits(
      [
        {
          action: 'crop_aspect',
          aspect,
          target,
          object: keep === 'object' ? object.trim() : '',
          position: keep === 'center' ? 'center' : keep,
          quote: `crop to ${aspect}`,
        },
      ],
      `Crop to ${aspect}`,
    );
  }
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Crop & rotate</h2>
        <p>
          Exact geometry, computed from the document ({width} × {height}).
        </p>
      </div>
      <Section title="CROP TO A SHAPE">
        <label className="field-label">
          Keep in frame
          <select value={keep} onChange={(event) => setKeep(event.target.value)}>
            <option value="center">The center</option>
            <option value="subject">The main subject (found by AI)</option>
            <option value="object">A named object…</option>
            <option value="top">The top</option>
            <option value="bottom">The bottom</option>
            <option value="left">The left side</option>
            <option value="right">The right side</option>
          </select>
        </label>
        {keep === 'object' && (
          <input
            aria-label="Object to keep"
            placeholder="the red car"
            value={object}
            onChange={(e) => setObject(e.target.value)}
          />
        )}
        <div className="pc-aspects">
          {ASPECTS.map((aspect) => {
            const [a, b] = aspect.split(':').map(Number);
            return (
              <button key={aspect} disabled={disabled} onClick={() => crop(aspect)}>
                <span style={{ aspectRatio: `${a} / ${b}` }} />
                {aspect}
              </button>
            );
          })}
        </div>
      </Section>
      <Section title="ROTATE & FLIP">
        <div className="pc-button-row">
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits(
                [
                  {
                    action: 'rotate',
                    value: 90,
                    choice: 'counterclockwise',
                    quote: 'rotate 90 counterclockwise',
                  },
                ],
                'Rotate left',
              )
            }
          >
            <RotateCcw size={14} /> 90°
          </button>
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits(
                [{ action: 'rotate', value: 90, choice: 'clockwise', quote: 'rotate 90 clockwise' }],
                'Rotate right',
              )
            }
          >
            <RotateCw size={14} /> 90°
          </button>
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits([{ action: 'flip', choice: 'horizontal', quote: 'flip horizontal' }], 'Flip horizontally')
            }
          >
            <FlipHorizontal2 size={14} />
          </button>
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits([{ action: 'flip', choice: 'vertical', quote: 'flip vertical' }], 'Flip vertically')
            }
          >
            <FlipVertical2 size={14} />
          </button>
        </div>
        <Slider
          label="Straighten"
          min={-15}
          max={15}
          step={0.1}
          value={angle}
          onChange={setAngle}
          format={(v) => `${v}°`}
        />
        <button
          className="button"
          disabled={disabled || !angle}
          onClick={() => {
            edits(
              [
                {
                  action: 'straighten',
                  value: Math.abs(angle),
                  choice: angle > 0 ? 'clockwise' : 'counterclockwise',
                  quote: `straighten ${Math.abs(angle)} degrees ${angle > 0 ? 'clockwise' : 'counterclockwise'}`,
                },
              ],
              `Straighten ${angle}°`,
            );
            setAngle(0);
          }}
        >
          Straighten (crops the empty corners)
        </button>
      </Section>
      <Section title="RESIZE">
        <div className="pc-inline">
          <input
            aria-label="Width in pixels"
            inputMode="numeric"
            placeholder={String(width)}
            value={size.w}
            onChange={(event) => {
              const w = event.target.value.replace(/\D/g, '');
              setSize({
                w,
                h: lock && w && width ? String(Math.round((Number(w) * height) / width)) : size.h,
              });
            }}
          />
          ×
          <input
            aria-label="Height in pixels"
            inputMode="numeric"
            placeholder={String(height)}
            value={size.h}
            onChange={(event) => {
              const h = event.target.value.replace(/\D/g, '');
              setSize({
                h,
                w: lock && h && height ? String(Math.round((Number(h) * width) / height)) : size.w,
              });
            }}
          />
          <label className="pc-check">
            <input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} />
            Keep shape
          </label>
        </div>
        <button
          className="button"
          disabled={disabled || !size.w || !size.h}
          onClick={() =>
            edits(
              [{ action: 'resize', quote: `resize to ${size.w}x${size.h}` }],
              `Resize to ${size.w}×${size.h}`,
            )
          }
        >
          Resize{!lock ? ' (crops first so nothing stretches)' : ''}
        </button>
      </Section>
      <Section title="BORDER">
        <div className="pc-inline">
          <input
            aria-label="Border size in pixels"
            type="number"
            min={1}
            max={2000}
            value={border}
            onChange={(e) => setBorder(Number(e.target.value))}
          />
          px
          <input
            aria-label="Border color"
            type="color"
            value={borderColor}
            onChange={(e) => setBorderColor(e.target.value)}
          />
          <button
            className="button"
            disabled={disabled || border < 1}
            onClick={() =>
              edits(
                [{ action: 'canvas_border', value: border, color: borderColor, quote: `${border}px border` }],
                `Add ${border}px border`,
              )
            }
          >
            Add border
          </button>
        </div>
      </Section>
    </div>
  );
}

/* ---------- Select & cut out ---------- */

export function SelectPanel({ document, busy, edits }: Actions) {
  const [subject, setSubject] = useState('');
  const [backdrop, setBackdrop] = useState('#ffffff');
  const [transparent, setTransparent] = useState(false);
  const [blur, setBlur] = useState<Edit['strength']>('moderate');
  const [remove, setRemove] = useState('');
  const [recolorObject, setRecolorObject] = useState('');
  const [recolor, setRecolor] = useState('#d62828');
  const [aiPrompt, setAiPrompt] = useState('');
  const disabled = !document || busy;
  const named = subject.trim();
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Select & cut out</h2>
        <p>The planner finds what you name; PhotoCraft outlines it precisely and every result is masked.</p>
      </div>
      <label className="field-label">
        Subject
        <input
          placeholder="Leave empty for the main subject, or name it: the woman, the car…"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
      </label>
      <Section title="REMOVE BACKGROUND">
        <div className="pc-inline">
          <label className="pc-check">
            <input type="checkbox" checked={transparent} onChange={(e) => setTransparent(e.target.checked)} />
            Transparent
          </label>
          {!transparent && (
            <input
              aria-label="Backdrop color"
              type="color"
              value={backdrop}
              onChange={(e) => setBackdrop(e.target.value)}
            />
          )}
          <button
            className="button"
            disabled={disabled}
            onClick={() =>
              edits(
                [
                  {
                    action: 'remove_background',
                    target: 'main subject',
                    object: named,
                    color: transparent ? '' : backdrop,
                    quote: 'remove the background',
                  },
                ],
                'Remove background',
              )
            }
          >
            Cut out
          </button>
        </div>
      </Section>
      <Section title="BLUR BACKGROUND">
        <Strength value={blur || 'moderate'} onChange={setBlur} />
        <button
          className="button"
          disabled={disabled}
          onClick={() =>
            edits(
              [
                {
                  action: 'blur_background',
                  target: named ? 'object' : 'main subject',
                  object: named,
                  strength: blur,
                  quote: 'blur the background',
                },
              ],
              'Blur background',
            )
          }
        >
          Blur behind the subject
        </button>
      </Section>
      <Section title="REMOVE AN OBJECT">
        <div className="pc-inline">
          <input
            aria-label="Object to remove"
            placeholder="the trash can on the left"
            value={remove}
            onChange={(e) => setRemove(e.target.value)}
          />
          <button
            className="button"
            disabled={disabled || !remove.trim()}
            onClick={() =>
              edits(
                [
                  {
                    action: 'remove_object',
                    target: 'object',
                    object: remove.trim(),
                    quote: `remove ${remove.trim()}`,
                  },
                ],
                `Remove ${remove.trim()}`,
              )
            }
          >
            Remove
          </button>
        </div>
        <small className="pc-muted">
          Small things use content-aware fill; larger ones are rebuilt by AI on their own layer.
        </small>
      </Section>
      <Section title="RECOLOR AN OBJECT">
        <div className="pc-inline">
          <input
            aria-label="Object to recolor"
            placeholder="her shirt"
            value={recolorObject}
            onChange={(e) => setRecolorObject(e.target.value)}
          />
          <input
            aria-label="New color"
            type="color"
            value={recolor}
            onChange={(e) => setRecolor(e.target.value)}
          />
          <button
            className="button"
            disabled={disabled || !recolorObject.trim()}
            onClick={() =>
              edits(
                [
                  {
                    action: 'recolor',
                    target: 'object',
                    object: recolorObject.trim(),
                    color: recolor,
                    quote: `make ${recolorObject.trim()} ${recolor}`,
                  },
                ],
                `Recolor ${recolorObject.trim()}`,
              )
            }
          >
            Recolor
          </button>
        </div>
      </Section>
      <Section title="PAINT NEW CONTENT WITH AI">
        <textarea
          rows={2}
          placeholder="Replace the sky with a stormy sky · add a small boat on the water"
          value={aiPrompt}
          onChange={(e) => setAiPrompt(e.target.value)}
        />
        <button
          className="button"
          disabled={disabled || !aiPrompt.trim()}
          onClick={() =>
            edits(
              [
                {
                  action: 'generate',
                  target: /\bsky\b/i.test(aiPrompt) ? 'sky' : 'whole image',
                  quote: aiPrompt.trim(),
                },
              ],
              `AI: ${aiPrompt.trim()}`,
            )
          }
        >
          <Wand2 size={14} />
          Paint as a new layer
        </button>
      </Section>
    </div>
  );
}

/* ---------- Text ---------- */

export function TextPanel({ document, busy, edits, fonts }: Actions & { fonts: string[] }) {
  const [text, setText] = useState('');
  const [font, setFont] = useState('');
  const [size, setSize] = useState('large');
  const [points, setPoints] = useState(48);
  const [color, setColor] = useState('#ffffff');
  const [auto, setAuto] = useState(true);
  const [position, setPosition] = useState('bottom');
  const [style, setStyle] = useState<string[]>([]);
  const layers = document ? flatten(document.state.layers) : [];
  const activeText = layers.find(
    (layer) => layer.id === document?.state.activeLayer && layer.kind === 'Type',
  );
  const [replacement, setReplacement] = useState('');
  const toggle = (name: string) =>
    setStyle(style.includes(name) ? style.filter((s) => s !== name) : [...style, name]);
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Text</h2>
        <p>Measured placement: the title is fitted inside the margins and kept readable.</p>
      </div>
      <label className="field-label">
        Words
        <textarea
          rows={2}
          value={text}
          placeholder="SUMMER 2026"
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <label className="field-label">
        Font
        <select value={font} onChange={(event) => setFont(event.target.value)}>
          <option value="">Default (Inter)</option>
          {['serif', 'script', 'impact', 'mono'].map((generic) => (
            <option key={generic} value={generic}>
              Any {generic}
            </option>
          ))}
          {fonts.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <div className="pc-segmented small" role="radiogroup" aria-label="Size">
        {['small', 'medium', 'large', 'huge', 'points'].map((id) => (
          <button
            key={id}
            role="radio"
            aria-checked={size === id}
            className={size === id ? 'on' : ''}
            onClick={() => setSize(id)}
          >
            {id === 'points' ? 'Exact pt' : id[0].toUpperCase() + id.slice(1)}
          </button>
        ))}
      </div>
      {size === 'points' && (
        <input
          aria-label="Size in points"
          type="number"
          min={4}
          max={1296}
          value={points}
          onChange={(e) => setPoints(Number(e.target.value))}
        />
      )}
      <div className="pc-text-grid">
        <div>
          <span className="field-label">Position</span>
          <PositionGrid value={position} onChange={setPosition} />
        </div>
        <div className="pc-text-options">
          <label className="pc-check">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            Readable color
          </label>
          {!auto && (
            <input
              aria-label="Text color"
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
            />
          )}
          {['bold', 'italic', 'shadow', 'outline', 'glow'].map((name) => (
            <label key={name} className="pc-check">
              <input type="checkbox" checked={style.includes(name)} onChange={() => toggle(name)} />
              {name[0].toUpperCase() + name.slice(1)}
            </label>
          ))}
        </div>
      </div>
      <button
        className="generate-button"
        disabled={!document || busy || !text.trim()}
        onClick={() =>
          edits(
            [
              {
                action: 'add_text',
                text: text.trim(),
                position,
                size: size === 'points' ? '' : size,
                value: size === 'points' ? points : null,
                quote: size === 'points' ? `${points}pt` : 'add text',
                color: auto ? '' : color,
                choice: [font, ...style].filter(Boolean).join(' '),
              },
            ],
            `Add “${text.trim().slice(0, 40)}”`,
          )
        }
      >
        Add text
      </button>
      {activeText && (
        <Section title="EDIT SELECTED TEXT">
          <input
            aria-label="New words"
            placeholder={activeText.text?.text}
            value={replacement}
            onChange={(e) => setReplacement(e.target.value)}
          />
          <button
            className="button"
            disabled={busy || !replacement.trim()}
            onClick={() =>
              edits(
                [
                  {
                    action: 'edit_text',
                    object: activeText.name,
                    text: replacement.trim(),
                    quote: 'change the text',
                  },
                ],
                `Change text to “${replacement.trim().slice(0, 30)}”`,
              )
            }
          >
            Change words
          </button>
        </Section>
      )}
    </div>
  );
}

/* ---------- Filters and all commands ---------- */

const FILTER_GROUPS: [string, string[]][] = [
  [
    'Blur',
    [
      'filter.blur.gaussianBlur',
      'filter.blur.lensBlur',
      'filter.blur.motionBlur',
      'filter.blurGallery.tiltShift',
      'filter.blurGallery.irisBlur',
      'filter.blurGallery.spinBlur',
      'filter.blur.surfaceBlur',
      'filter.blur.radialBlur',
    ],
  ],
  ['Sharpen', ['filter.sharpen.smartSharpen', 'filter.sharpen.unsharpMask', 'filter.other.highPass']],
  [
    'Noise',
    [
      'filter.noise.reduceNoise',
      'filter.noise.addNoise',
      'filter.noise.dustAndScratches',
      'filter.noise.median',
    ],
  ],
  ['Develop', ['filter.cameraRaw', 'filter.lensCorrection']],
  ['Light', ['filter.render.relight', 'filter.render.lightingEffects', 'filter.render.lensFlare']],
  [
    'Artistic',
    [
      'filter.stylize.oilPaint',
      'filter.gallery.watercolor',
      'filter.gallery.coloredPencil',
      'filter.gallery.cutout',
      'filter.gallery.dryBrush',
      'filter.gallery.posterEdges',
      'filter.gallery.inkOutlines',
      'filter.gallery.paintDaubs',
      'filter.gallery.sumiE',
    ],
  ],
  [
    'Stylize',
    [
      'filter.stylize.emboss',
      'filter.stylize.findEdges',
      'filter.stylize.solarize',
      'filter.stylize.diffuse',
      'filter.stylize.wind',
      'filter.stylize.tiles',
    ],
  ],
];

function CommandRunner({
  command,
  actions,
  onPhoto,
}: {
  command: Command;
  actions: Actions;
  onPhoto: boolean;
}) {
  const [params, setParams] = useState<Record<string, unknown>>({});
  const filter = command.id.startsWith('filter.');
  return (
    <div className="pc-command-editor">
      <h3>{command.label.replace('…', '')}</h3>
      <small className="pc-muted">{command.id}</small>
      {command.runnable ? (
        <>
          <FieldForm
            fields={command.fields}
            layers={actions.document?.state.layers || []}
            onChange={setParams}
            resetKey={command.id}
          />
          <button
            className="generate-button"
            disabled={!actions.document || actions.busy}
            onClick={() =>
              actions.commands(
                [
                  ...(filter && onPhoto
                    ? [{ command: 'studio.select_photo', params: { smart: true }, label: 'Select the photo' }]
                    : []),
                  { command: command.id, params, label: command.label },
                ],
                command.label.replace('…', ''),
              )
            }
          >
            <Play size={14} />
            Apply {filter && onPhoto ? 'as a smart filter' : ''}
          </button>
        </>
      ) : (
        <p className="pc-muted">{command.reason}</p>
      )}
    </div>
  );
}

export function FiltersPanel(props: Actions & { commands_list: Command[] }) {
  const byId = useMemo(
    () => Object.fromEntries(props.commands_list.map((c) => [c.id, c])),
    [props.commands_list],
  );
  const [chosen, setChosen] = useState('filter.blur.gaussianBlur');
  const command = byId[chosen];
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Filters</h2>
        <p>Applied to the photo as editable smart filters; toggle or delete them from the layer later.</p>
      </div>
      {FILTER_GROUPS.map(([group, ids]) => (
        <Section key={group} title={group.toUpperCase()}>
          <div className="pc-chip-list">
            {ids
              .filter((id) => byId[id])
              .map((id) => (
                <button key={id} className={chosen === id ? 'on' : ''} onClick={() => setChosen(id)}>
                  {byId[id].label.replace('…', '')}
                </button>
              ))}
          </div>
        </Section>
      ))}
      {command && <CommandRunner command={command} actions={props} onPhoto />}
    </div>
  );
}

export function CommandsPanel(props: Actions & { commands_list: Command[]; discovered: number }) {
  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState<Command | null>(null);
  const [limit, setLimit] = useState(80);
  const query = search.toLowerCase().trim();
  const matches = props.commands_list.filter(
    (item) =>
      !query || `${item.id} ${item.label} ${(item.menu || []).join(' ')}`.toLowerCase().includes(query),
  );
  const runnable = props.commands_list.filter((c) => c.runnable).length;
  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>All tools</h2>
        <p>
          Every one of PhotoCraft’s {props.discovered} engine commands, with real controls. {runnable} run
          here; the rest need the desktop app (files, preferences, plug-ins).
        </p>
      </div>
      <label className="pc-search">
        <Search size={14} />
        <input
          aria-label="Search PhotoCraft tools"
          placeholder="Curves, mask, warp, text, liquify…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <div className="pc-command-list">
        {matches.slice(0, limit).map((item) => (
          <button
            key={item.id}
            className={chosen?.id === item.id ? 'on' : ''}
            onClick={() => setChosen(item)}
          >
            <span>{item.label.replace('…', '')}</span>
            <small>
              {(item.menu || []).join(' › ') || item.category}
              {!item.runnable && ' · desktop'}
            </small>
          </button>
        ))}
      </div>
      <small className="pc-muted">
        {matches.length} match{matches.length === 1 ? '' : 'es'}
        {matches.length > limit && (
          <button className="text-button" onClick={() => setLimit(limit + 100)}>
            {' '}
            Show more
          </button>
        )}
      </small>
      {chosen && <CommandRunner command={chosen} actions={props} onPhoto={false} />}
    </div>
  );
}
