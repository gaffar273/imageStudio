import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  Eye,
  EyeOff,
  FolderHeart,
  ImagePlus,
  Layers,
  LoaderCircle,
  RotateCcw,
  Save,
  Send,
  Square,
  Upload,
  X,
} from 'lucide-react';
import { api, readImage } from '../lib/api';
import type { StudioImage } from '../lib/types';
interface KritaState {
  connected: boolean;
  state: {
    name: string;
    width: number;
    height: number;
    selection?: boolean;
    layers: { name: string; visible: boolean; active: boolean; depth: number }[];
  } | null;
  events: Record<string, unknown>[];
  preview: boolean;
  preview_version: number;
}
export function Krita({
  error,
  notify,
  images,
}: {
  error: (value: string) => void;
  notify: (value: string) => void;
  images: StudioImage[];
}) {
  const [state, setState] = useState<KritaState | null>(null);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [query, setQuery] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  useEffect(() => {
    let active = true;
    let timer: number;
    async function refresh() {
      try {
        const data = await api<KritaState>('/krita');
        if (active) {
          setState(data);
          setConnectionError(false);
        }
      } catch {
        if (active) setConnectionError(true);
      }
      if (active) timer = window.setTimeout(refresh, 2000);
    }
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (choosing) picker.current?.showModal();
    else picker.current?.close();
  }, [choosing]);
  const connected = !!state?.connected && !connectionError;
  const document = state?.state;
  const documentName = document?.name.replace(/^import-[a-f0-9]{32}\.png$/, 'Imported image');
  const hasDocument = connected && !!document;
  async function command(action: string, image?: string) {
    if (pending.current) return;
    pending.current = true;
    setSending(true);
    try {
      const result = await api<{ message: string }>('/krita', { action, text, image });
      notify(result.message);
      if (action === 'prompt') setText('');
      if (action === 'open') setChoosing(false);
    } catch (err) {
      error(String(err));
    } finally {
      pending.current = false;
      setSending(false);
    }
  }
  async function upload(file?: File) {
    if (!file || pending.current) return;
    pending.current = true;
    setSending(true);
    try {
      const image = await readImage(file);
      const result = await api<{ message: string }>('/krita', { action: 'import', image });
      notify(result.message);
    } catch (err) {
      error(String(err));
    } finally {
      pending.current = false;
      setSending(false);
    }
  }
  return (
    <div className="page-content krita-page">
      <input
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        className="sr-only"
        aria-label="Upload image to Krita"
        disabled={sending}
        onChange={(event) => {
          void upload(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      <div className="krita-connection-bar">
        <span>
          <i className={connected ? 'dot' : 'dot offline'} />
          {connectionError
            ? 'Connection lost. Retrying…'
            : connected
              ? 'Krita connected'
              : 'Open Krita to connect'}
        </span>
        <button className="button" disabled={sending} onClick={() => command('launch')}>
          Open Krita
          <ArrowUpRight size={16} />
        </button>
      </div>
      <div className="krita-workspace">
        <section
          className={`krita-canvas-panel ${dragging ? 'dragging' : ''}`}
          aria-label="Canvas preview"
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void upload(event.dataTransfer.files[0]);
          }}
        >
          <div className="krita-canvas-heading">
            <div>
              <span className="eyebrow">{hasDocument ? 'ACTIVE DOCUMENT' : 'YOUR CANVAS'}</span>
              <h2>{hasDocument ? documentName : 'Start with an image'}</h2>
            </div>
            {hasDocument && (
              <span className="muted">
                {document.width} × {document.height}
              </span>
            )}
          </div>
          <div className="krita-stage">
            {hasDocument && state?.preview ? (
              <img
                className="krita-preview"
                src={`/api/krita/preview?v=${state.preview_version}`}
                alt="Live Krita canvas"
              />
            ) : (
              <div className="krita-empty">
                <ImagePlus size={36} strokeWidth={1.4} />
                <h3>{hasDocument ? 'Your preview is on its way' : 'A place for your next idea'}</h3>
                <p>
                  {hasDocument
                    ? 'Your canvas will appear here as Krita updates.'
                    : 'Drop an image here or upload one to open it in Krita.'}
                </p>
                {!hasDocument && (
                  <button className="button" disabled={sending} onClick={() => fileInput.current?.click()}>
                    <Upload size={16} />
                    Upload image
                  </button>
                )}
              </div>
            )}
            {dragging && (
              <div className="krita-drop-overlay">
                <Upload size={28} />
                Drop to open in Krita
              </div>
            )}
          </div>
          <div className="krita-canvas-caption">
            <span>
              {hasDocument
                ? 'Live preview · Paint and select areas in Krita.'
                : 'Images open as a new document in Krita.'}
            </span>
            {hasDocument && document.selection && <span className="selection-badge">Selection active</span>}
          </div>
          {document && !connected && (
            <p className="krita-offline-note">
              Reconnect Krita to see the current canvas and use editing tools.
            </p>
          )}
        </section>
        <aside className="krita-tools" aria-label="Canvas tools">
          <section className="krita-tool-section">
            <h3>Add to your workspace</h3>
            <div className="krita-import-actions">
              <button className="button" disabled={sending} onClick={() => fileInput.current?.click()}>
                <Upload size={16} />
                Upload image
              </button>
              <button className="button" disabled={sending} onClick={() => setChoosing(true)}>
                <FolderHeart size={16} />
                From library
              </button>
            </div>
            <button
              className="text-button krita-new"
              disabled={!connected || sending}
              onClick={() => command('new_canvas')}
            >
              <ImagePlus size={15} />
              New blank canvas <span>1024 × 1024</span>
            </button>
            <p className="muted">Opens a new document. Your current canvas stays open in Krita.</p>
          </section>
          <section className="krita-tool-section">
            <label className="krita-instruction-label" htmlFor="krita-instruction">
              What would you like to change?
            </label>
            <textarea
              id="krita-instruction"
              aria-label="Krita instruction"
              placeholder="Make the background warmer and bring out the details…"
              value={text}
              maxLength={6000}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (
                  (event.ctrlKey || event.metaKey) &&
                  event.key === 'Enter' &&
                  connected &&
                  text.trim() &&
                  !sending
                ) {
                  event.preventDefault();
                  void command('prompt');
                }
              }}
            />
            <p className="muted">
              {hasDocument && document.selection
                ? 'Your edit will use the selection made in Krita.'
                : 'Describe an edit, or ask for a new image.'}
            </p>
            <button
              className="generate-button"
              disabled={!connected || !text.trim() || sending}
              onClick={() => command('prompt')}
            >
              {sending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}Send to canvas
            </button>
            <div className="krita-history-actions">
              <button className="button" disabled={!hasDocument || sending} onClick={() => command('undo')}>
                <RotateCcw size={15} />
                Undo
              </button>
              <button className="button" disabled={!connected} onClick={() => command('stop')}>
                <Square size={15} />
                Stop
              </button>
              <button className="button" disabled={!hasDocument || sending} onClick={() => command('save')}>
                <Save size={15} />
                Save to library
              </button>
            </div>
          </section>
          <section className="krita-tool-section">
            <h3>
              <Layers size={16} />
              Layers <span className="muted">{hasDocument ? document.layers.length : 0}</span>
            </h3>
            {hasDocument && document.layers.length ? (
              <div className="krita-layer-list">
                {document.layers.map((layer, index) => (
                  <div
                    key={index}
                    className={layer.active ? 'active' : ''}
                    style={{ paddingLeft: `${10 + Math.min(layer.depth, 5) * 10}px` }}
                  >
                    {layer.visible ? (
                      <Eye size={14} aria-label="Visible" />
                    ) : (
                      <EyeOff size={14} aria-label="Hidden" />
                    )}
                    <span>{layer.name}</span>
                    {layer.active && <small>Active</small>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">Layers appear when a document is open.</p>
            )}
            {hasDocument && <p className="muted">Manage layers in Krita.</p>}
          </section>
        </aside>
      </div>
      {!!state?.events.length && (
        <details className="krita-activity">
          <summary>
            Canvas activity{' '}
            <span>{String(state.events.at(-1)?.text || state.events.at(-1)?.kind || 'Canvas updated')}</span>
          </summary>
          <div aria-live="polite">
            {state.events
              .slice(-10)
              .reverse()
              .map((event, index) => (
                <p key={index} className={event.kind === 'failed' ? 'activity-error' : ''}>
                  <span className="dot" />
                  {String(event.text || event.message || event.kind || 'Canvas updated')}
                </p>
              ))}
          </div>
        </details>
      )}
      <dialog
        ref={picker}
        className="krita-library-picker"
        onCancel={() => setChoosing(false)}
        onClose={() => setChoosing(false)}
      >
        <div className="krita-picker-heading">
          <div>
            <h2>Open from your library</h2>
            <p className="muted">Choose an image to open as a new document in Krita.</p>
          </div>
          <button
            className="icon-button"
            aria-label="Close library picker"
            onClick={() => setChoosing(false)}
          >
            <X size={20} />
          </button>
        </div>
        <input
          aria-label="Search library images"
          placeholder="Search your images…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="krita-picker-grid">
          {images
            .filter((image) =>
              `${image.name} ${image.metadata.request || image.metadata.prompt || ''}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((image) => (
              <button
                key={image.name}
                disabled={sending}
                onClick={() => command('open', image.name)}
                title={image.metadata.request || image.metadata.prompt || image.name}
              >
                <img
                  src={image.thumbnail}
                  alt={image.metadata.request || image.metadata.prompt || image.name}
                  loading="lazy"
                />
                <span>{image.metadata.request || image.metadata.prompt || image.name}</span>
              </button>
            ))}
        </div>
        {!images.length && (
          <p className="muted">Your library is empty. Upload an image or create one first.</p>
        )}
        {!!images.length &&
          !images.some((image) =>
            `${image.name} ${image.metadata.request || image.metadata.prompt || ''}`
              .toLowerCase()
              .includes(query.toLowerCase()),
          ) && <p className="muted">No images match your search.</p>}
      </dialog>
    </div>
  );
}
