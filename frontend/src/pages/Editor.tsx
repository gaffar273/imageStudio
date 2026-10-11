import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  Brush,
  Eraser,
  ImagePlus,
  LoaderCircle,
  Sparkles,
  Square,
  Upload,
  X,
} from 'lucide-react';
import type { Config, Job } from '../lib/types';
import { api, readImage } from '../lib/api';
import { Range, Toggle } from '../components/Controls';
interface Props {
  source: string;
  onSource: (value: string) => void;
  config: Config;
  job: Job | null;
  busy: boolean;
  submit: (body: unknown) => void;
  cancel: () => void;
  error: (message: string) => void;
  onWorkspace: () => void;
}
export function Editor({ source, onSource, config, job, busy, submit, cancel, error, onWorkspace }: Props) {
  const [prompt, setPrompt] = useState('');
  const [engine, setEngine] = useState(config.photocraft ? 'photocraft' : 'kontext');
  const photoCraft = engine === 'photocraft';
  const [brush, setBrush] = useState(false);
  const [brushSize, setBrushSize] = useState(35);
  const [smart, setSmart] = useState(false);
  const [painted, setPainted] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const previous = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    setPainted(false);
  }, [source]);
  async function upload(file?: File) {
    if (file)
      try {
        onSource(await readImage(file));
      } catch (err) {
        error(String(err));
      }
  }
  function paint(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current || !brush) return;
    const node = canvas.current!;
    const rect = node.getBoundingClientRect();
    const context = node.getContext('2d')!;
    const point = {
      x: ((event.clientX - rect.left) * node.width) / rect.width,
      y: ((event.clientY - rect.top) * node.height) / rect.height,
    };
    context.strokeStyle = 'white';
    context.lineWidth = (brushSize * node.width) / rect.width;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.beginPath();
    context.moveTo(previous.current?.x ?? point.x, previous.current?.y ?? point.y);
    context.lineTo(point.x + 0.01, point.y);
    context.stroke();
    previous.current = point;
    setPainted(true);
  }
  const result = job?.images.at(-1);
  return (
    <div className="editor-layout">
      <section className="edit-controls">
        <div className="panel-heading">
          <span>
            <Sparkles size={17} />A fresh perspective
          </span>
        </div>
        <div className="edit-controls-body">
          <p className="muted">Describe the light, color, or content you want to change.</p>
          {config.photocraft && (
            <button className="button" onClick={onWorkspace}>
              Open full PhotoCraft workspace
            </button>
          )}
          <label className="field-label">
            Editing tool
            <select
              aria-label="Editing tool"
              value={engine}
              disabled={busy}
              onChange={(e) => {
                setEngine(e.target.value);
                setBrush(false);
                setPainted(false);
                canvas.current
                  ?.getContext('2d')
                  ?.clearRect(0, 0, canvas.current.width, canvas.current.height);
              }}
            >
              <option value="photocraft" disabled={!config.photocraft}>
                PhotoCraft — light and color
              </option>
              <option value="kontext" disabled={!config.editing}>
                AI content editing
              </option>
            </select>
          </label>
          <label className="field-label">
            Describe your edit
            <textarea
              aria-label="Edit instruction"
              placeholder={
                photoCraft
                  ? 'Make it brighter and warmer, or try professional polish…'
                  : 'Change the background to a sunlit garden. Keep the person and their expression…'
              }
              rows={7}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </label>
          <div className="inspiration-chips">
            {(photoCraft
              ? [
                  'Professional polish',
                  'Warm portrait',
                  'Cinematic teal and orange',
                  'Soft faded film',
                  'Make it grayscale',
                ]
              : ['Make it golden hour', 'Turn it into a watercolor', 'Remove the background']
            ).map((text) => (
              <button key={text} onClick={() => setPrompt(text)}>
                {text}
                <span>↗</span>
              </button>
            ))}
          </div>
          {!photoCraft && (
            <Toggle
              label="Smart edit prompt"
              checked={smart}
              disabled={!config.assistant}
              onChange={setSmart}
            />
          )}
          <div className="divider" />
          {!photoCraft && (
            <Toggle
              label="Paint an area to edit"
              description="Only the painted area will change"
              checked={brush}
              onChange={setBrush}
            />
          )}
          {brush && (
            <>
              <Range label="Brush size" min={5} max={120} value={brushSize} onChange={setBrushSize} />
              <button
                className="button"
                onClick={() => {
                  canvas.current
                    ?.getContext('2d')
                    ?.clearRect(0, 0, canvas.current.width, canvas.current.height);
                  setPainted(false);
                }}
              >
                <Eraser size={15} />
                Clear mask
              </button>
            </>
          )}
          <div className="editor-model">
            <Sparkles size={20} />
            <div>
              <strong>{photoCraft ? 'PhotoCraft' : 'FLUX.1 Kontext'}</strong>
              <small>
                {photoCraft
                  ? 'Whole-photo adjustments · Editable PSD layers'
                  : config.editing
                    ? 'Ready for a new perspective'
                    : 'Download the editing model to begin'}
              </small>
            </div>
          </div>
          <button
            className="generate-button"
            disabled={busy || !source || !prompt.trim() || !(photoCraft ? config.photocraft : config.editing)}
            onClick={() =>
              submit({
                image: source,
                engine,
                mask: painted ? canvas.current?.toDataURL('image/png') : null,
                prompt,
                smart,
              })
            }
          >
            <Sparkles size={17} />
            Apply edit
          </button>
        </div>
      </section>
      <div className="edit-stage">
        <div className="canvas-topline">
          <span>
            {brush ? <Brush size={15} /> : <ImagePlus size={15} />}{' '}
            {brush ? 'Paint over the area you want to change' : 'Your image, with new possibilities'}
          </span>
          {source && (
            <button className="text-button" onClick={() => onSource('')}>
              <X size={14} />
              Remove
            </button>
          )}
        </div>
        <div
          className={`upload-stage ${source ? 'has-image' : ''}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            upload(e.dataTransfer.files[0]);
          }}
        >
          {source ? (
            <div className="paint-container">
              <img
                src={source}
                alt="Image to edit"
                onLoad={(e) => {
                  if (canvas.current) {
                    canvas.current.width = e.currentTarget.naturalWidth;
                    canvas.current.height = e.currentTarget.naturalHeight;
                    setPainted(false);
                  }
                }}
              />
              <canvas
                ref={canvas}
                aria-label="Paint edit mask"
                className={brush ? 'painting' : ''}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  drawing.current = true;
                  previous.current = null;
                  paint(e);
                }}
                onPointerMove={paint}
                onPointerUp={() => {
                  drawing.current = false;
                  previous.current = null;
                }}
                onPointerCancel={() => {
                  drawing.current = false;
                }}
              />
            </div>
          ) : (
            <label className="upload-target">
              <span className="upload-symbol">
                <Upload size={30} />
              </span>
              <h2>Every image has another story.</h2>
              <p>Drop a photo here, or click to browse.</p>
              <span className="button">
                Choose an image
                <Upload size={14} />
              </span>
              <small>PNG, JPG, WEBP · Up to 25 MB</small>
              <input type="file" accept="image/*" onChange={(e) => upload(e.target.files?.[0])} />
            </label>
          )}
        </div>
        {job && (
          <div className="job-status" role="status">
            <div>
              {busy && <LoaderCircle size={16} className="spin" />}
              <span>{job.message}</span>
              {busy && (
                <button className="text-button" onClick={cancel}>
                  <Square size={13} />
                  Stop
                </button>
              )}
            </div>
            {busy && (
              <div className="progress-track">
                <span style={{ width: `${Math.max(3, job.progress * 100)}%` }} />
              </div>
            )}
          </div>
        )}
        {result && (
          <div className="edited-result">
            <div className="recent-heading">
              <h3>Your new perspective</h3>
              <div>
                {result.metadata.layered_document && (
                  <>
                    <button
                      className="button"
                      onClick={async () => {
                        try {
                          await api(`/photocraft/${result.name}/open`, {});
                        } catch (err) {
                          error(String(err));
                        }
                      }}
                    >
                      Open in PhotoCraft
                    </button>
                    <a className="button" href={`/api/photocraft/${result.name}/download`}>
                      Download PSD
                    </a>
                  </>
                )}
                <button className="button" onClick={() => onSource(result.url)}>
                  Keep editing
                </button>
                <a className="button" href={`/api/library/${result.name}/download`}>
                  <ArrowDownToLine size={15} />
                  Download
                </a>
              </div>
            </div>
            <img src={result.url} alt="Edited result" />
          </div>
        )}
      </div>
    </div>
  );
}
