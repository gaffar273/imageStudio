import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FolderOpen, ImagePlus, Plus } from 'lucide-react';

export interface ProjectImage {
  id: string; name: string; width: number; height: number; thumbnail: string;
}
export interface ProjectSummary {
  id: string; name: string; width?: number; height?: number; preview?: string; updated?: number; images?: number;
}

export function ProjectHome({ editor, projects, busy, onNew, onOpen, onImage, onResume, children }: {
  editor: string; projects: ProjectSummary[]; busy: boolean;
  onNew: () => void; onOpen: () => void; onImage: () => void; onResume: (id: string) => void; children?: ReactNode;
}) {
  const [query, setQuery] = useState('');
  const visible = projects.filter((project) => project.name.toLowerCase().includes(query.toLowerCase()));
  return <section className="project-home">
    <span className="eyebrow">YOUR WORKSPACE</span><h1>{editor} projects</h1>
    <p>Your images, layers and edits, saved together. Start a new project or continue where you left off.</p>
    {children}
    <div className="project-actions">
      <button className="generate-button" disabled={busy} onClick={onNew}><Plus size={17} /> New project</button>
      <button className="button" disabled={busy} onClick={onOpen}><FolderOpen size={17} /> Open project file</button>
      <button className="button" disabled={busy} onClick={onImage}><ImagePlus size={17} /> Start from an image</button>
    </div>
    <p className="muted">Changes are saved on this computer. Save a project file for a portable copy or backup.</p>
    <input aria-label={`Search ${editor} projects`} placeholder="Search your projects…" value={query} onChange={(event) => setQuery(event.target.value)} />
    <div className="project-grid">{visible.map((project) => <button key={project.id} className="project-card" disabled={busy} onClick={() => onResume(project.id)}>
      {project.preview ? <img src={project.preview} alt="" /> : <FolderOpen size={35} />}
      <strong>{project.name}</strong><small>{project.width ? `${project.width} × ${project.height} · ` : ''}{project.images || 0} source images</small>
      {project.updated && <small>Saved {new Date(project.updated * 1000).toLocaleString()}</small>}
    </button>)}</div>
    {!visible.length && <p className="muted">{projects.length ? 'No projects match your search.' : 'No projects yet. Create one, then import the images you want to work with.'}</p>}
  </section>;
}

export function NewProject({ editor, onCreate, onClose }: {
  editor: string; onCreate: (values: { name: string; width: number; height: number }) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState('Untitled project');
  const [width, setWidth] = useState(1600);
  const [height, setHeight] = useState(1000);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="project-dialog" onCancel={onClose}>
    <form onSubmit={(event) => { event.preventDefault(); onCreate({ name: name.trim(), width, height }); }}>
      <h2>New {editor} project</h2><p className="muted">Choose your canvas. Images can be imported and arranged after creating the project.</p>
      <label className="field-label">Project name<input required maxLength={150} autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label>
      <div className="project-actions">
        <label className="field-label">Width (px)<input type="number" min={1} max={8192} required value={width} onChange={(event) => setWidth(Number(event.target.value))} /></label>
        <label className="field-label">Height (px)<input type="number" min={1} max={8192} required value={height} onChange={(event) => setHeight(Number(event.target.value))} /></label>
      </div>
      <div className="project-actions">{([['Landscape', 1600, 1000], ['Square', 1080, 1080], ['Portrait', 1080, 1350]] as const).map(([title, w, h]) =>
        <button key={title} type="button" className="button" onClick={() => { setWidth(w); setHeight(h); }}>{title}</button>)}</div>
      {width * height > 40_000_000 && <p role="alert">Choose a canvas of at most 40 megapixels.</p>}
      <div className="project-actions"><button type="submit" className="generate-button" disabled={!name.trim() || width * height > 40_000_000}>Create project</button>
        <button type="button" className="button" onClick={onClose}>Cancel</button></div>
    </form>
  </dialog>;
}

export function ProjectAssets({ images, busy, onImport, onPlace }: {
  images: ProjectImage[]; busy: boolean; onImport: () => void;
  onPlace: (image: ProjectImage, values: { fit?: boolean; as_canvas?: boolean; x?: number; y?: number }) => void;
}) {
  return <section className="project-assets" aria-label="Project images">
    <div className="project-assets-heading"><strong>Project images</strong><span>Drag onto the canvas, or choose Place.</span>
      <button className="button" disabled={busy} onClick={onImport}><Plus size={15} /> Import images</button></div>
    <div className="project-image-strip">{images.map((image) => <article className="project-image" key={image.id} draggable={!busy}
      onDragStart={(event) => { event.dataTransfer.setData('application/x-image-studio-project-image', image.id); event.dataTransfer.effectAllowed = 'copy'; }}>
      <img src={image.thumbnail} alt={image.name} draggable={false} /><strong title={image.name}>{image.name}</strong>
      <small>{image.width} × {image.height} px</small>
      <select aria-label={`Place ${image.name}`} value="" disabled={busy} onChange={(event) => {
        const mode = event.target.value; if (mode) onPlace(image, mode === 'canvas' ? { as_canvas: true } : { fit: mode === 'fit' });
      }}><option value="">Place…</option><option value="original">Place at original size</option>
        <option value="fit">Fit inside canvas</option><option value="canvas">Use as new canvas</option></select>
    </article>)}
      {!images.length && <p className="muted">Import your source images here. They stay in the project; the canvas changes only when you place one.</p>}
    </div>
  </section>;
}
