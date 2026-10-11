import {
  Aperture,
  ArrowUpRight,
  FolderHeart,
  ImagePlus,
  Layers,
  SlidersHorizontal,
  Sparkles,
  SquarePen,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import type { Page } from '../lib/types';
const items: { id: Page; label: string; icon: typeof Sparkles; caption?: string }[] = [
  { id: 'create', label: 'Create image', icon: Sparkles },
  { id: 'edit', label: 'Edit image', icon: SquarePen },
  { id: 'photocraft', label: 'PhotoCraft studio', icon: Layers },
  { id: 'library', label: 'My library', icon: FolderHeart },
  { id: 'krita', label: 'Krita canvas', icon: ImagePlus },
];
export function Sidebar({
  page,
  onNavigate,
  collapsed,
  onCollapse,
}: {
  page: Page;
  onNavigate: (page: Page) => void;
  collapsed: boolean;
  onCollapse: () => void;
}) {
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <a className="brand" href="#create" onClick={() => onNavigate('create')} aria-label="Image Studio home">
        <span className="brand-mark">
          <Aperture size={25} strokeWidth={1.8} />
        </span>
        <span>
          image<span className="brand-light">studio</span>
          <small>CREATIVE WORKSPACE</small>
        </span>
      </a>
      <div className="nav-label">WORKSPACE</div>
      <nav>
        {items.map(({ id, label, icon: Icon }) => (
          <button
            title={label}
            key={id}
            className={`nav-item ${page === id ? 'active' : ''}`}
            onClick={() => onNavigate(id)}
          >
            <Icon size={19} />
            <span>{label}</span>
            {id === 'create' && <span className="nav-spark">✧</span>}
          </button>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <button
          title="Studio settings"
          className={`nav-item ${page === 'settings' ? 'active' : ''}`}
          onClick={() => onNavigate('settings')}
        >
          <SlidersHorizontal size={18} />
          <span>Studio settings</span>
          <ArrowUpRight size={14} />
        </button>
        <div className="sidebar-footer">
          <span className="avatar">ME</span>
          <div>
            <strong>Personal workspace</strong>
            <small>Private by design</small>
          </div>
          <button
            className="icon-button"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            onClick={onCollapse}
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
      </div>
    </aside>
  );
}
