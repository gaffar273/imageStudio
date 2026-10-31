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
import { api } from '../lib/api';
import type { StudioImage } from '../lib/types';
import { NewProject, ProjectAssets, ProjectHome, type ProjectImage, type ProjectSummary } from '../photocraft/Projects';
import { LayerArrange } from '../photocraft/LayerArrange';
import '../projects.css';
interface KritaProject extends ProjectSummary { assets: ProjectImage[]; saved?: boolean; can_restore?: boolean; save_error?: string }
interface KritaState {
  connected: boolean;
  state: {
    name: string;
    width: number;
    height: number;
    selection?: boolean;
    layers: { id?: string; name: string; visible: boolean; active: boolean; depth: number; kind?: string; bounds?: number[]; opacity?: number; locked?: boolean }[];
    activeLayer?: string;
    modified?: boolean;
    save_error?: string;
  } | null;
  events: Record<string, unknown>[];
  preview: boolean;
  preview_version: number;
  project?: KritaProject | null;
  capabilities?: { projects?: boolean };
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
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<KritaProject | null>(null);
  const [home, setHome] = useState(true);
  const [newProject, setNewProject] = useState(false);
  const [arranging, setArranging] = useState(false);
  const [stageNode, setStageNode] = useState<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState({ width: 700, height: 450 });
  const frame = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const layerInput = useRef<HTMLInputElement>(null);
  const projectInput = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  function loadProjects() { api<{ projects: ProjectSummary[] }>('/krita/projects').then((result) => setProjects(result.projects)).catch(() => {}); }
  useEffect(loadProjects, []);
  useEffect(() => {
    if (!stageNode) return;
    const observer = new ResizeObserver(([entry]) => { if (entry) setStageSize({ width: entry.contentRect.width, height: entry.contentRect.height }); });
    observer.observe(stageNode); return () => observer.disconnect();
  }, [stageNode]);
  useEffect(() => {
    let active = true;
    let timer: number;
    async function refresh() {
      try {
        const data = await api<KritaState>('/krita');
        if (active) {
          setState(data);
          if (data.project) setProject((current) => current?.id === data.project!.id ? data.project! : current);
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
  const hasDocument = connected && !!document && (!project || state?.project?.id === project.id);
  async function projectCall(path: string, body: object) {
    if (pending.current) return;
    pending.current = true; setSending(true);
    try {
      const result = await api<{ project: KritaProject; closed?: boolean; message: string }>(path, body);
      if (result.closed) { setProject(null); setHome(true); }
      else { setProject(result.project); setHome(false); }
      setState(await api<KritaState>('/krita'));
      loadProjects(); notify(result.message); return result.project;
    } catch (err) { error(String(err)); }
    finally { pending.current = false; setSending(false); }
  }
  function projectAction(action: string) {
    if (action === 'close' && state?.project?.id !== project?.id) { setProject(null); setHome(true); return; }
    if (project) void projectCall(`/krita/projects/${project.id}/action`, { action });
  }
  function layerAction(id: string | undefined, operation: string, values: object = {}) {
    if (project && id) void projectCall(`/krita/projects/${project.id}/layers/${id}`, { operation, ...values });
  }
  function placeAsset(asset: ProjectImage, values: { fit?: boolean; as_canvas?: boolean; x?: number; y?: number }) {
    if (project) void projectCall(`/krita/projects/${project.id}/assets/${asset.id}/place`, values);
  }
  async function command(action: string, image?: string) {
    if (action === 'open' && image) { await projectCall('/krita/projects/from-library', { name: image }); setChoosing(false); return; }
    if (action === 'new_canvas') { setNewProject(true); return; }
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
      if (!file.size || file.size > 500_000_000) throw new Error('Choose a project under 500 MB.');
      const body = new FormData(); body.append('file', file);
      const response = await fetch('/api/krita/projects/import', { method: 'POST', body });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not open the project.');
      setProject(result.project); setHome(false); setState(await api<KritaState>('/krita')); loadProjects();
      notify(result.message);
    } catch (err) {
      error(String(err));
    } finally {
      pending.current = false;
      setSending(false);
    }
  }
  async function addLayers(files: File[]) {
    if (!files.length || pending.current || !project) return;
    if (
      files.length > 16 ||
      files.some((file) => !file.size) ||
      files.reduce((total, file) => total + file.size, 0) > 100_000_000
    ) {
      error('Choose up to 16 nonempty images totaling at most 100 MB.');
      return;
    }
    pending.current = true;
    setSending(true);
    try {
      const body = new FormData();
      files.forEach((file) => body.append('files', file));
      const response = await fetch(`/api/krita/projects/${project.id}/assets`, { method: 'POST', body });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not add image layers.');
      setProject(result.project);
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
      <input ref={projectInput} type="file" accept=".istudio,.kra" hidden aria-label="Open Krita project file"
        onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = ''; }} />
      <input
        ref={layerInput}
        type="file"
        multiple
        accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        className="sr-only"
        aria-label="Import Krita project images"
        disabled={sending || !hasDocument}
        onChange={(event) => {
          void addLayers(Array.from(event.target.files || []));
          event.target.value = '';
        }}
      />
      {newProject && <NewProject editor="Krita" onClose={() => setNewProject(false)} onCreate={(values) => {
        setNewProject(false); void projectCall('/krita/projects', values);
      }} />}
      {home ? <ProjectHome editor="Krita" projects={projects} busy={sending || !connected}
        onNew={() => setNewProject(true)} onOpen={() => projectInput.current?.click()}
        onImage={() => fileInput.current?.click()} onResume={(id) => void projectCall(`/krita/projects/${id}/action`, { action: 'open' })}>
        <p>{connected ? 'Krita is connected.' : 'Open Krita to start or resume a project.'}</p>
        {!connected && <button className="button" disabled={sending} onClick={() => void command('launch')}>Open Krita to connect</button>}
        {connected && hasDocument && !state?.project && <button className="button" disabled={sending} onClick={() => {
          const name = window.prompt('Project name', documentName || 'Untitled project')?.trim();
          if (name) void projectCall('/krita/projects', { name, use_current: true });
        }}>Save the open Krita canvas as a project</button>}
      </ProjectHome> : <>
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
      <div className="project-canvas-tools"><strong>{project?.name || documentName}</strong>
        <span title={document?.save_error}>{document?.save_error ? 'Save failed — retry Save' : sending || document?.modified ? 'Saving…' : 'Saved on this computer'}</span>
        <button className="button" disabled={sending || arranging} onClick={() => setNewProject(true)}>New project</button>
        <a className="button" aria-disabled={sending || arranging || !hasDocument} onClick={(event) => { if (sending || arranging || !hasDocument) event.preventDefault(); }} href={project ? `/api/krita/projects/${project.id}/file` : undefined} download={`${project?.name}.istudio`}>Save project file</a>
        <button className="button" disabled={sending || arranging} onClick={() => projectAction('clear')}>Clear canvas</button>
        {project?.can_restore && <button className="button" disabled={sending} onClick={() => projectAction('restore')}>Restore previous canvas</button>}
        <button className="button" disabled={sending || arranging} onClick={() => projectAction('close')}>Close project</button>
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
            const files = Array.from(event.dataTransfer.files);
            const asset = event.dataTransfer.getData('application/x-image-studio-project-image');
            const rect = frame.current?.getBoundingClientRect();
            if (asset && project && document && rect) { const image = project.assets.find((item) => item.id === asset);
              if (image) placeAsset(image, { x: (event.clientX - rect.left) * document.width / rect.width,
                y: (event.clientY - rect.top) * document.height / rect.height });
            } else if (files.length === 1 && /\.(kra|istudio)$/i.test(files[0]!.name)) void upload(files[0]);
            else if (hasDocument) void addLayers(files);
            else if (files.length === 1) void upload(files[0]);
            else if (files.length) error('Open a background first, then add the other images as layers.');
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
          <div className="krita-stage" ref={setStageNode}>
            {hasDocument && state?.preview ? (
              <div ref={frame} style={{ position: 'relative', width: document.width * Math.min(stageSize.width / document.width, stageSize.height / document.height),
                height: document.height * Math.min(stageSize.width / document.width, stageSize.height / document.height) }}><img
                className="krita-preview"
                src={`/api/krita/preview?v=${state.preview_version}`}
                alt="Live Krita canvas"
              />
                {project && <LayerArrange frame={frame} width={document.width} height={document.height}
                  layers={document.layers.filter((layer) => layer.id).map((layer) => ({ ...layer, id: layer.id! }))}
                  active={document.activeLayer || null} revision={state.preview_version} busy={sending}
                  preview={(id, part) => `/api/krita/projects/${project.id}/layers/${id}/preview/${state.preview_version}/${part}`}
                  onSelect={(id) => void projectCall(`/krita/projects/${project.id}/layers/${id}`, { operation: 'select' })}
                  onTransform={(id, values) => void projectCall(`/krita/projects/${project.id}/layers/${id}`, { operation: 'transform', ...values })}
                  onDrawing={setArranging} />}
              </div>
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
                {hasDocument ? 'Drop to save source images in this project' : 'Drop to start a project'}
              </div>
            )}
          </div>
          {project && <ProjectAssets images={project.assets} busy={sending} onImport={() => layerInput.current?.click()} onPlace={placeAsset} />}
          <div className="krita-canvas-caption">
            <span>
              {hasDocument
                ? 'Live preview · Import sources below, choose Place, then drag to move or resize an image.'
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
              className="button"
              disabled={sending || !hasDocument}
              onClick={() => layerInput.current?.click()}
            >
              <ImagePlus size={16} /> Import project images
            </button>
            <button
              className="text-button krita-new"
              disabled={!connected || sending}
              onClick={() => command('new_canvas')}
            >
              <ImagePlus size={15} />
              New blank canvas <span>1024 × 1024</span>
            </button>
            <p className="muted">Source images stay in the project. Place an image when you want it on the canvas.</p>
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
                    <button className="icon-button" aria-label={`${layer.visible ? 'Hide' : 'Show'} ${layer.name}`} disabled={sending || !project || layer.locked || !layer.id} onClick={() => layerAction(layer.id, 'visibility', { visible: !layer.visible })}>{layer.visible ? (
                      <Eye size={14} aria-label="Visible" />
                    ) : (
                      <EyeOff size={14} aria-label="Hidden" />
                    )}</button>
                    <button className="button" disabled={sending || !project || !layer.id} onClick={() => layerAction(layer.id, 'select')}>{layer.name}</button>
                    {layer.active && <small>Active</small>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">Layers appear when a document is open.</p>
            )}
            {hasDocument && <p className="muted">Select a layer to move or resize it on the canvas. More layer tools are available in Krita.</p>}
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
      </>}
    </div>
  );
}
