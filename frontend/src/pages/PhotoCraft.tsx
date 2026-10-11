import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowLeftRight,
  Command as CommandIcon,
  Crop,
  FolderOpen,
  Images,
  Layers,
  LoaderCircle,
  Palette,
  PanelRight,
  Plus,
  Redo2,
  ScanSearch,
  SlidersHorizontal,
  Sparkles,
  Square,
  Type,
  Undo2,
  Wand2,
  X,
} from 'lucide-react';
import { api } from '../lib/api';
import type { StudioImage } from '../lib/types';
import { AssistantPanel } from '../photocraft/AssistantPanel';
import { Canvas } from '../photocraft/Canvas';
import { Inspector } from '../photocraft/Inspector';
import {
  AdjustPanel,
  CommandsPanel,
  CropPanel,
  FiltersPanel,
  LooksPanel,
  SelectPanel,
  TextPanel,
} from '../photocraft/ToolPanels';
import type { Actions, Capabilities, CraftDocument, CraftJob, Edit, Plan } from '../photocraft/types';
import '../photocraft.css';

interface Props {
  images: StudioImage[];
  error: (message: string) => void;
  initialSource?: string;
  consumed: () => void;
}

const TOOLS = [
  { id: 'assistant', label: 'Assistant', icon: Sparkles },
  { id: 'adjust', label: 'Adjust', icon: SlidersHorizontal },
  { id: 'looks', label: 'Looks', icon: Palette },
  { id: 'crop', label: 'Crop', icon: Crop },
  { id: 'select', label: 'Select', icon: ScanSearch },
  { id: 'text', label: 'Text', icon: Type },
  { id: 'filters', label: 'Filters', icon: Wand2 },
  { id: 'all', label: 'All tools', icon: CommandIcon },
] as const;
type Tool = (typeof TOOLS)[number]['id'];

const CANVAS_SIZES: [string, number, number][] = [
  ['Landscape 1600 × 1000', 1600, 1000],
  ['Square 1080 × 1080', 1080, 1080],
  ['Portrait 1080 × 1350', 1080, 1350],
  ['Story 1080 × 1920', 1080, 1920],
  ['Full HD 1920 × 1080', 1920, 1080],
  ['A4 at 150 ppi 1240 × 1754', 1240, 1754],
];

function store(key: string, value?: string) {
  try {
    if (value === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* Resuming is optional. */
  }
}

export function PhotoCraft({ images, error, initialSource, consumed }: Props) {
  const [document, setDocument] = useState<CraftDocument | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [fonts, setFonts] = useState<string[]>([]);
  const [recent, setRecent] = useState<{ id: string; name: string; updated: number }[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [job, setJob] = useState<CraftJob | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('Your instructions, your layers, your original intact.');
  const [tool, setTool] = useState<Tool>(() => {
    try {
      return (localStorage.getItem('studio:photocraft-tool') as Tool) || 'assistant';
    } catch {
      return 'assistant';
    }
  });
  const [compare, setCompare] = useState(false);
  const [zoom, setZoom] = useState(0);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [library, setLibrary] = useState(false);
  const [inspector, setInspector] = useState(true);
  const [menu, setMenu] = useState<'' | 'export' | 'new' | 'recent'>('');
  const uploadInput = useRef<HTMLInputElement>(null);
  const importedSource = useRef('');
  const busy = pending || job?.state === 'running';

  function remember(next: CraftDocument) {
    setDocument(next);
    store('studio:photocraft-workspace', next.id);
  }

  function accept(next: CraftJob) {
    setJob(next);
    setMessage(next.message);
    if (next.workspace) {
      remember(next.workspace);
      setPlan((current) => (current && current.revision !== next.workspace?.revision ? null : current));
    }
    if (next.plan) setPlan(next.plan);
    if (next.state === 'error') error(next.message);
    if (next.state === 'running') store('studio:photocraft-job', next.id);
  }

  useEffect(() => {
    api<Capabilities>('/photocraft/capabilities')
      .then(setCapabilities)
      .catch((err) => error(String(err)));
    api<{ fonts: string[] }>('/photocraft/fonts')
      .then((value) => setFonts(value.fonts))
      .catch(() => {});
    api<{ workspaces: { id: string; name: string; updated: number }[] }>('/photocraft/workspaces')
      .then((value) => setRecent(value.workspaces))
      .catch(() => {});
    try {
      const id = localStorage.getItem('studio:photocraft-workspace');
      if (id && !initialSource)
        api<CraftDocument>(`/photocraft/workspaces/${id}`)
          .then(remember)
          .catch(() => store('studio:photocraft-workspace'));
      const jobId = localStorage.getItem('studio:photocraft-job');
      if (jobId)
        api<CraftJob>(`/jobs/${jobId}`)
          .then(accept)
          .catch(() => store('studio:photocraft-job'));
    } catch {
      /* Resuming is optional. */
    }
  }, []);

  useEffect(() => store('studio:photocraft-tool', tool), [tool]);

  useEffect(() => {
    if (!job || job.state !== 'running') return;
    let stopped = false;
    let timer: number;
    const poll = async () => {
      try {
        const next = await api<CraftJob>(`/jobs/${job.id}`);
        if (stopped) return;
        if (next.state !== 'running') {
          accept(next);
          store('studio:photocraft-job');
          return;
        }
        setJob(next);
        setMessage(next.message);
        timer = window.setTimeout(poll, 900);
      } catch {
        if (!stopped) {
          setMessage('Connection interrupted. Reconnecting…');
          timer = window.setTimeout(poll, 2500);
        }
      }
    };
    poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [job?.id, job?.state]);

  async function submit(path: string, body: unknown) {
    setPending(true);
    try {
      accept(await api<CraftJob>(path, body));
    } catch (err) {
      error(String(err));
      setMessage(String(err).replace(/^Error: /, ''));
    } finally {
      setPending(false);
    }
  }

  async function upload(file?: File) {
    if (!file || busy) return;
    if (file.size > 100_000_000) {
      error('Choose a document under 100 MB.');
      return;
    }
    setPending(true);
    setMessage('Opening your document…');
    try {
      const body = new FormData();
      body.append('file', file);
      const response = await fetch('/api/photocraft/workspaces/import', { method: 'POST', body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not open the document.');
      setPlan(null);
      accept(data);
      setLibrary(false);
      setZoom(0);
    } catch (err) {
      error(String(err));
    } finally {
      setPending(false);
    }
  }

  async function fromLibrary(url: string, name = 'Library image.png') {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Image not found.');
      await upload(new File([await response.blob()], name));
    } catch (err) {
      error(String(err));
    }
  }

  useEffect(() => {
    if (initialSource && importedSource.current !== initialSource) {
      importedSource.current = initialSource;
      fromLibrary(initialSource);
      consumed();
    }
  }, [initialSource]);

  function operation(body: object) {
    if (document)
      submit(`/photocraft/workspaces/${document.id}/operation`, { revision: document.revision, ...body });
  }

  const actions: Actions = {
    document,
    busy,
    error,
    edits: (edits: Edit[], label: string) => {
      if (document)
        submit(`/photocraft/workspaces/${document.id}/edits`, { revision: document.revision, edits, label });
    },
    commands: (commands, label) => operation({ commands, label }),
  };

  useEffect(() => {
    function keys(event: KeyboardEvent) {
      const typing = (event.target as HTMLElement)?.closest('input, textarea, select');
      if (typing || !document || busy || !(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === 'z' && !event.shiftKey && document.can_undo) {
        event.preventDefault();
        operation({ action: 'undo' });
      } else if (
        (event.key.toLowerCase() === 'y' || (event.key.toLowerCase() === 'z' && event.shiftKey)) &&
        document.can_redo
      ) {
        event.preventDefault();
        operation({ action: 'redo' });
      }
    }
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  });

  const exports = document ? `/api/photocraft/workspaces/${document.id}/export/${document.revision}` : '';
  const regions = plan && plan.revision === document?.revision ? plan.regions || [] : [];

  return (
    <div className={`pc ${inspector ? '' : 'no-inspector'}`} onClick={() => menu && setMenu('')}>
      <input
        ref={uploadInput}
        hidden
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.tif,.tiff,.psd,.psb,.pcraft,.ora,.bmp"
        onChange={(event) => {
          upload(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      <header className="pc-bar">
        <div className="pc-title">
          <span className="pc-title-icon">
            <Layers size={17} />
          </span>
          <div>
            <strong>{document?.name || 'PhotoCraft studio'}</strong>
            <small>
              {document
                ? `${document.state.width} × ${document.state.height} px · ${document.state.mode} ${document.state.depth}-bit · revision ${document.cursor + 1} of ${document.history.length}`
                : capabilities && !capabilities.installed
                  ? 'PhotoCraft is not installed'
                  : 'Open a photo or document to begin'}
            </small>
          </div>
        </div>
        <div className="pc-bar-group">
          <button
            className="icon-button"
            aria-label="Undo"
            title="Undo (Ctrl+Z)"
            disabled={busy || !document?.can_undo}
            onClick={() => operation({ action: 'undo' })}
          >
            <Undo2 size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="Redo"
            title="Redo (Ctrl+Y)"
            disabled={busy || !document?.can_redo}
            onClick={() => operation({ action: 'redo' })}
          >
            <Redo2 size={16} />
          </button>
          <span className="pc-divider" />
          <button
            className={`pc-bar-button ${compare ? 'on' : ''}`}
            disabled={!document}
            onClick={() => setCompare(!compare)}
            aria-pressed={compare}
          >
            <ArrowLeftRight size={14} />
            Compare
          </button>
          <select
            aria-label="Zoom"
            value={zoom}
            disabled={!document}
            onChange={(event) => setZoom(Number(event.target.value))}
          >
            <option value={0}>Fit</option>
            {[25, 50, 100, 200].map((value) => (
              <option key={value} value={value}>
                {value}%
              </option>
            ))}
          </select>
        </div>
        <div className="pc-bar-group" onClick={(event) => event.stopPropagation()}>
          <button
            className="pc-bar-button"
            disabled={busy || !capabilities?.installed}
            onClick={() => uploadInput.current?.click()}
          >
            <FolderOpen size={14} />
            Open
          </button>
          <button className="pc-bar-button" onClick={() => setLibrary(!library)} aria-pressed={library}>
            <Images size={14} />
            Library
          </button>
          <div className="pc-menu-anchor">
            <button
              className="pc-bar-button"
              disabled={busy || !capabilities?.installed}
              onClick={() => setMenu(menu === 'new' ? '' : 'new')}
            >
              <Plus size={14} />
              New
            </button>
            {menu === 'new' && (
              <div className="pc-menu">
                {CANVAS_SIZES.map(([label, width, height]) => (
                  <button
                    key={label}
                    onClick={() => {
                      setMenu('');
                      setPlan(null);
                      submit('/photocraft/workspaces', { name: 'Untitled canvas', width, height });
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          {recent.length > 0 && (
            <div className="pc-menu-anchor">
              <button
                className="pc-bar-button"
                disabled={busy}
                onClick={() => setMenu(menu === 'recent' ? '' : 'recent')}
              >
                Recent
              </button>
              {menu === 'recent' && (
                <div className="pc-menu">
                  {recent.slice(0, 12).map((item) => (
                    <button
                      key={item.id}
                      onClick={() => {
                        setMenu('');
                        setPlan(null);
                        api<CraftDocument>(`/photocraft/workspaces/${item.id}`)
                          .then(remember)
                          .catch((err) => error(String(err)));
                      }}
                    >
                      {item.name}
                      <small>{new Date(item.updated * 1000).toLocaleString()}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {document && (
            <div className="pc-menu-anchor">
              <button
                className="pc-bar-button primary"
                onClick={() => setMenu(menu === 'export' ? '' : 'export')}
              >
                <ArrowDownToLine size={14} />
                Export
              </button>
              {menu === 'export' && (
                <div className="pc-menu right">
                  {[
                    ['psd', 'PSD · layered, for Photoshop'],
                    ['pcraft', 'PCraft · native, every layer'],
                    ['tif', 'TIFF · print'],
                    ['png', 'PNG · lossless'],
                    ['jpg', 'JPEG · sharing'],
                    ['webp', 'WebP · web'],
                  ].map(([format, label]) => (
                    <a key={format} href={`${exports}/${format}`} onClick={() => setMenu('')}>
                      {label}
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            className={`icon-button pc-inspector-toggle ${inspector ? 'on' : ''}`}
            aria-label="Show layers"
            aria-pressed={inspector}
            onClick={() => setInspector(!inspector)}
          >
            <PanelRight size={16} />
          </button>
        </div>
      </header>
      <div className="pc-body">
        <nav className="pc-rail" aria-label="PhotoCraft tools">
          {TOOLS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={tool === id ? 'active' : ''}
              aria-current={tool === id}
              onClick={() => setTool(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <section className="pc-panel" aria-label={TOOLS.find((t) => t.id === tool)?.label}>
          {tool === 'assistant' && (
            <AssistantPanel
              document={document}
              busy={busy}
              brain={!!capabilities?.brain}
              plan={plan}
              onPlan={(prompt) => {
                if (!document) return;
                setPlan(null);
                setHighlight(null);
                submit(`/photocraft/workspaces/${document.id}/plan`, { revision: document.revision, prompt });
              }}
              onApply={(partial) => plan && operation({ plan_id: plan.id, partial })}
              onDiscard={() => setPlan(null)}
              onHighlight={setHighlight}
            />
          )}
          {tool === 'adjust' && <AdjustPanel {...actions} />}
          {tool === 'looks' && <LooksPanel {...actions} />}
          {tool === 'crop' && <CropPanel {...actions} />}
          {tool === 'select' && <SelectPanel {...actions} />}
          {tool === 'text' && <TextPanel {...actions} fonts={fonts} />}
          {tool === 'filters' && <FiltersPanel {...actions} commands_list={capabilities?.commands || []} />}
          {tool === 'all' && (
            <CommandsPanel
              {...actions}
              commands_list={capabilities?.commands || []}
              discovered={capabilities?.discovered || 0}
            />
          )}
        </section>
        <main className="pc-stage">
          <Canvas
            document={document}
            compare={compare}
            zoom={zoom}
            regions={regions}
            highlight={highlight}
            busy={busy}
            onOpen={() => uploadInput.current?.click()}
            onLibrary={() => setLibrary(true)}
            onDrop={upload}
          />
          {library && (
            <div className="pc-library">
              <div className="pc-section-head">
                <strong>Open from your library</strong>
                <button className="icon-button" aria-label="Close library" onClick={() => setLibrary(false)}>
                  <X size={14} />
                </button>
              </div>
              <div>
                {images.slice(0, 24).map((image) => (
                  <button
                    key={image.name}
                    disabled={busy}
                    onClick={() => fromLibrary(image.url, image.name)}
                    title={image.metadata.prompt || image.name}
                  >
                    <img src={image.thumbnail} alt={image.metadata.prompt || 'Library image'} />
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="pc-status" role="status">
            <span>
              {busy ? <LoaderCircle size={13} className="spin" /> : <span className="pc-status-dot" />}
              {message}
            </span>
            {job?.state === 'running' && (
              <button
                className="text-button"
                onClick={() =>
                  api(`/jobs/${job.id}/cancel`, {})
                    .then(() => setMessage('Stopping after the current step…'))
                    .catch((err) => error(String(err)))
                }
              >
                <Square size={11} />
                Stop
              </button>
            )}
            {busy && (
              <span className="pc-progress">
                <span style={{ width: `${Math.max(4, (job?.progress || 0) * 100)}%` }} />
              </span>
            )}
          </div>
        </main>
        {inspector && (
          <Inspector
            {...actions}
            onGoto={(index) => operation({ action: 'goto', index })}
            onDesktop={() => operation({ action: 'desktop' })}
            onSync={() => operation({ action: 'sync' })}
          />
        )}
      </div>
    </div>
  );
}
