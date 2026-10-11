import { useCallback, useEffect, useState } from 'react';
import { Check, ChevronRight, CircleHelp, LoaderCircle, Plus, X } from 'lucide-react';
import type { Config, Job, Learned, Page, Settings, StudioImage } from './lib/types';
import { api } from './lib/api';
import { Sidebar } from './components/Sidebar';
import { PromptPanel } from './components/PromptPanel';
import { Workspace } from './components/Workspace';
import { ImageDialog } from './components/ImageDialog';
import { HelpDialog } from './components/HelpDialog';
import { Library } from './pages/Library';
import { Editor } from './pages/Editor';
import { PhotoCraft } from './pages/PhotoCraft';
import { Krita } from './pages/Krita';
import { StudioSettings } from './pages/StudioSettings';

const titles: Record<Page, string> = {
  create: 'Create image',
  edit: 'Edit image',
  photocraft: 'PhotoCraft studio',
  library: 'My library',
  krita: 'Krita canvas',
  settings: 'Studio settings',
};
const defaults: Settings = {
  prompt: '',
  model: 'realistic',
  size: '',
  seed: '',
  steps: 30,
  guidance: 5,
  negative_prompt: '',
  detail: 'Off',
  detail_strength: 0.35,
  count: 1,
  smart: false,
  sketch: null,
  sketch_freedom: 0.65,
  vary: true,
  check: false,
  attempts: 2,
  repair: true,
  repair_strength: 0.3,
  photo_style: 'Natural photo',
  photo_finish: 'Light',
  combine: true,
  references: true,
  realism: 0.6,
  personal: 0.5,
};
function readStored<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback;
  } catch {
    return fallback;
  }
}
function getPage(): Page {
  const value = window.location.hash.slice(1);
  return value in titles ? (value as Page) : 'create';
}
export default function App() {
  const [page, setPage] = useState<Page>(getPage);
  const [collapsed, setCollapsed] = useState(false);
  const [config, setConfig] = useState<Config | null>(null);
  const [online, setOnline] = useState(false);
  const [settings, setSettings] = useState<Settings>(defaults);
  const [images, setImages] = useState<StudioImage[]>([]);
  const [selected, setSelected] = useState<StudioImage | null>(null);
  const [favorites, setFavorites] = useState<string[]>(() => readStored('studio:favorites', []));
  const [job, setJob] = useState<Job | null>(null);
  const [editJob, setEditJob] = useState<Job | null>(null);
  const [activeJob, setActiveJob] = useState<{ id: string; kind: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [editorSource, setEditorSource] = useState('');
  const [photoSource, setPhotoSource] = useState('');
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const [bootError, setBootError] = useState('');
  const [libraryResults, setLibraryResults] = useState<StudioImage[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [help, setHelp] = useState(false);
  const busy = submitting || activeJob !== null;
  const notify = useCallback((message: string) => setToast({ message, error: false }), []);
  const error = useCallback(
    (message: string) => setToast({ message: message.replace(/^Error: /, ''), error: true }),
    [],
  );
  const navigate = useCallback((next: Page) => {
    window.location.hash = next;
    setPage(next);
  }, []);
  const refreshImages = useCallback(async () => {
    const result = await api<{ images: StudioImage[] }>('/library');
    setImages(result.images);
  }, []);
  const update = useCallback(
    (patch: Partial<Settings>) => setSettings((previous) => ({ ...previous, ...patch })),
    [],
  );
  useEffect(() => {
    const listener = () => setPage(getPage());
    window.addEventListener('hashchange', listener);
    return () => window.removeEventListener('hashchange', listener);
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([api<Config>('/config'), api<{ images: StudioImage[] }>('/library')])
      .then(([data, library]) => {
        if (!active) return;
        setConfig(data);
        setImages(library.images);
        setOnline(true);
        syncFavorites();
        const saved = readStored<Partial<Settings>>('studio:settings', {});
        setSettings({
          ...defaults,
          negative_prompt: data.negative_prompt,
          size: data.sizes[0].id,
          ...saved,
          sketch: null,
          repair: data.repair && (saved.repair ?? true),
          references: data.references && (saved.references ?? true),
          smart: data.assistant && (saved.smart ?? false),
          check: data.assistant && (saved.check ?? false),
        });
        const storedJob = readStored<{ id: string; kind: string } | null>('studio:active-job', null);
        if (data.active_job)
          setActiveJob({
            id: data.active_job,
            kind: storedJob?.id === data.active_job ? storedJob.kind : 'generate',
          });
      })
      .catch((err) => {
        if (active) setBootError(String(err));
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (config)
      try {
        localStorage.setItem('studio:settings', JSON.stringify({ ...settings, sketch: null }));
      } catch {
        /* Storage can be disabled in private browsers. */
      }
  }, [settings, config]);
  useEffect(() => {
    try {
      localStorage.setItem('studio:favorites', JSON.stringify(favorites));
    } catch {
      /* Favorites remain available for this session. */
    }
  }, [favorites]);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), toast.error ? 12000 : 5000);
    return () => clearTimeout(id);
  }, [toast]);
  useEffect(() => {
    if (!activeJob) return;
    let disposed = false;
    let timeout: number;
    let failures = 0;
    const poll = async () => {
      try {
        const current = await api<Job>(`/jobs/${activeJob.id}`);
        if (disposed) return;
        failures = 0;
        setOnline(true);
        if (activeJob.kind === 'edit') setEditJob(current);
        else if (activeJob.kind !== 'sketch') setJob(current);
        if (current.state !== 'running') {
          if (current.state === 'error') error(current.message);
          if (current.sketch) {
            update({ sketch: current.sketch });
            notify('Composition sketch ready.');
          }
          setActiveJob(null);
          localStorage.removeItem('studio:active-job');
          await refreshImages();
          return;
        }
      } catch (err) {
        if (disposed) return;
        failures++;
        setOnline(false);
        if (failures >= 5) {
          error(`Lost connection to the render. Refresh to reconnect. ${String(err)}`);
          setActiveJob(null);
          return;
        }
      }
      if (!disposed) timeout = window.setTimeout(poll, 1000);
    };
    poll();
    return () => {
      disposed = true;
      clearTimeout(timeout);
    };
  }, [activeJob, error, notify, refreshImages, update]);
  useEffect(() => {
    const id = window.setInterval(
      () =>
        api('/health')
          .then(() => setOnline(true))
          .catch(() => setOnline(false)),
      15000,
    );
    return () => clearInterval(id);
  }, []);
  async function submit(kind: string, body: unknown) {
    setSubmitting(true);
    try {
      const result = await api<Job>(`/${kind}`, body);
      const active = { id: result.id, kind };
      setActiveJob(active);
      if (kind === 'edit') setEditJob(result);
      else if (kind === 'generate') setJob(result);
      try {
        localStorage.setItem('studio:active-job', JSON.stringify(active));
      } catch {
        /* Optional reconnect hint. */
      }
    } catch (err) {
      error(String(err));
    } finally {
      setSubmitting(false);
    }
  }
  function generate() {
    if (!config || busy || !settings.prompt.trim()) return;
    if (settings.seed && Number(settings.seed) > 4294967295) {
      error('Seed must be between 0 and 4294967295.');
      return;
    }
    submit('generate', { ...settings, seed: settings.seed === '' ? null : Number(settings.seed) });
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && page === 'create') {
        event.preventDefault();
        generate();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  });
  async function cancel() {
    if (activeJob)
      try {
        await api(`/jobs/${activeJob.id}/cancel`, {});
        notify('Stopping after the current step…');
      } catch (err) {
        error(String(err));
      }
  }
  // Favorites live on the server too: the personal style LoRA learns from them.
  async function syncFavorites() {
    try {
      const local = readStored<string[]>('studio:favorites', []);
      const server = (await api<{ names: string[] }>('/favorites')).names;
      let names = server;
      for (const name of local.filter((value) => !server.includes(value)))
        try {
          names = (await api<{ names: string[] }>('/favorites', { name, favorite: true })).names;
        } catch {
          /* An image that was deleted from the library. */
        }
      setFavorites(names);
    } catch {
      /* Keep the browser's favorites when the server is older. */
    }
  }
  function favorite(name: string) {
    const on = !favorites.includes(name);
    setFavorites((previous) => (on ? [...previous, name] : previous.filter((value) => value !== name)));
    api('/favorites', { name, favorite: on }).catch(() => {
      /* Still kept in this browser. */
    });
  }
  function applyLearnedSettings(profile: Learned['profile']) {
    if (!config) return;
    const size = profile.size && config.sizes.find((item) => item.id.endsWith(profile.size!))?.id;
    update({
      ...(profile.model ? { model: profile.model } : {}),
      ...(size ? { size } : {}),
      ...(profile.finish ? { photo_finish: profile.finish } : {}),
      ...(profile.realism != null ? { realism: profile.realism } : {}),
    });
    navigate('create');
    notify('Your usual settings are loaded.');
  }
  function reuse(image: StudioImage) {
    if (!config) return;
    const meta = image.metadata;
    const combined = Boolean(meta.texture_from);
    const model =
      combined || meta.model?.includes('Z-Image')
        ? 'accurate'
        : meta.model?.includes('sdxl-turbo')
          ? 'turbo'
          : 'realistic';
    update({
      prompt: meta.request || meta.prompt || '',
      seed: meta.seed != null ? String(meta.seed) : '',
      model,
      size:
        config.sizes.find(
          (size) =>
            size.width === (meta.base_width || meta.width) &&
            size.height === (meta.base_height || meta.height),
        )?.id || config.sizes[0].id,
      steps: combined ? 9 : meta.steps || 30,
      guidance: meta.guidance ?? 5,
      negative_prompt: meta.negative_prompt ?? config.negative_prompt,
      photo_style: meta.style || 'Polished',
      photo_finish: meta.finish || 'Off',
      detail: meta.detail_pass?.option || 'Off',
      detail_strength: meta.detail_pass?.strength ?? 0.35,
      realism: meta.realism_lora?.strength ?? 0,
      personal: meta.personal_lora?.strength ?? 0,
      combine: combined,
      sketch: null,
    });
    setSelected(null);
    navigate('create');
    notify('Settings loaded. Keep the seed, or clear it for a new variation.');
  }
  async function openKrita(image: StudioImage) {
    try {
      const result = await api<{ message: string }>('/krita', { action: 'open', image: image.name });
      notify(result.message);
      setSelected(null);
      navigate('krita');
    } catch (err) {
      error(String(err));
    }
  }
  async function visualSearch(query: string) {
    setSearching(true);
    try {
      const data = await api<{ images: StudioImage[] }>(`/library/search?q=${encodeURIComponent(query)}`);
      setLibraryResults(data.images);
    } catch (err) {
      error(String(err));
    } finally {
      setSearching(false);
    }
  }
  async function findSimilar(image: StudioImage) {
    setSearching(true);
    try {
      const data = await api<{ images: StudioImage[] }>(
        `/library/search?similar=${encodeURIComponent(image.name)}`,
      );
      setLibraryResults(data.images);
      setSelected(null);
      navigate('library');
    } catch (err) {
      error(String(err));
    } finally {
      setSearching(false);
    }
  }
  return (
    <div className="studio-app">
      <Sidebar
        page={page}
        onNavigate={navigate}
        collapsed={collapsed}
        onCollapse={() => setCollapsed(!collapsed)}
      />
      <main className={`main-shell ${page === 'photocraft' ? 'photocraft-mode' : ''}`}>
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{titles[page]}</strong>
          </div>
          <div className="topbar-right">
            {!online && (
              <span className="private-pill">
                <span className="dot offline" />
                Reconnecting
              </span>
            )}
            <button
              className="icon-button"
              aria-label="How to use Image Studio"
              onClick={() => setHelp(true)}
            >
              <CircleHelp size={18} />
            </button>
            <span className="avatar">ME</span>
          </div>
        </header>
        {page !== 'photocraft' && (
          <div className="page-heading">
            <div>
              <div className="heading-kicker">YOUR IMAGINATION, MADE VISIBLE</div>
              <h1>
                {titles[page]}
                <span className="heading-dot">.</span>
              </h1>
              <p>
                {page === 'create'
                  ? 'Big ideas start with a few words.'
                  : page === 'edit'
                    ? 'A small change can tell a whole new story.'
                    : page === 'library'
                      ? 'A little world of your own making.'
                      : page === 'krita'
                        ? 'Add an image, describe an edit, and continue in Krita.'
                        : 'Make yourself at home.'}
              </p>
            </div>
            <button
              className="button new-creation"
              onClick={() => {
                update({ prompt: '', seed: '', sketch: null });
                if (!busy) setJob(null);
                navigate('create');
              }}
            >
              <Plus size={16} />
              New creation
            </button>
          </div>
        )}
        {!config ? (
          <div className="page-empty">
            {bootError ? (
              <>
                <h2>Let’s reconnect your studio.</h2>
                <p>{bootError}</p>
                <button className="button" onClick={() => window.location.reload()}>
                  Try again
                </button>
              </>
            ) : (
              <>
                <LoaderCircle size={30} className="spin" />
                <p>Opening your creative workspace…</p>
              </>
            )}
          </div>
        ) : (
          <>
            {page === 'create' && (
              <div className="create-layout">
                <PromptPanel
                  config={config}
                  settings={settings}
                  update={update}
                  busy={busy}
                  generate={generate}
                  sketch={() => submit('sketch', { prompt: settings.prompt, size: settings.size })}
                  error={error}
                />
                <Workspace
                  images={images}
                  job={job}
                  onCancel={cancel}
                  onSelect={setSelected}
                  onLibrary={() => navigate('library')}
                  onPrompt={(prompt) => update({ prompt })}
                  favorites={favorites}
                  onFavorite={favorite}
                />
              </div>
            )}
            {page === 'library' && (
              <Library
                images={libraryResults || images}
                favorites={favorites}
                onFavorite={favorite}
                onSelect={setSelected}
                semantic={visualSearch}
                onReset={() => {
                  setLibraryResults(null);
                  refreshImages().catch((err) => error(String(err)));
                }}
                searching={searching}
              />
            )}
            {page === 'edit' && (
              <Editor
                source={editorSource}
                onSource={setEditorSource}
                config={config}
                job={editJob}
                busy={busy}
                submit={(body) => submit('edit', body)}
                cancel={cancel}
                error={error}
                onWorkspace={() => {
                  setPhotoSource(editorSource);
                  navigate('photocraft');
                }}
              />
            )}
            {page === 'photocraft' && (
              <PhotoCraft
                images={images}
                error={error}
                initialSource={photoSource}
                consumed={() => setPhotoSource('')}
              />
            )}
            {page === 'krita' && <Krita error={error} notify={notify} images={images} />}{' '}
            {page === 'settings' && (
              <StudioSettings
                config={config}
                notify={notify}
                error={error}
                onUseSettings={applyLearnedSettings}
              />
            )}
          </>
        )}
        {page !== 'photocraft' && (
          <footer className="main-footer">
            <span>
              IMAGE STUDIO <span className="footer-dot">/</span> MADE FOR THE WAY YOU IMAGINE.
            </span>
            <span>
              Made for your imagination.<span className="footer-star">✧</span>
            </span>
          </footer>
        )}
      </main>
      {selected && (
        <ImageDialog
          image={selected}
          close={() => setSelected(null)}
          reuse={() => reuse(selected)}
          edit={() => {
            setEditorSource(selected.url);
            setSelected(null);
            navigate('edit');
          }}
          krita={() => openKrita(selected)}
          similar={() => findSimilar(selected)}
          favorite={favorites.includes(selected.name)}
          onFavorite={() => favorite(selected.name)}
        />
      )}
      {toast && (
        <div className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}>
          {toast.error ? <CircleHelp size={18} /> : <Check size={18} />}
          <span>{toast.message}</span>
          <button aria-label="Dismiss notification" className="icon-button" onClick={() => setToast(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      {help && <HelpDialog close={() => setHelp(false)} />}
    </div>
  );
}
