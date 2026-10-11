import { useEffect, useState } from 'react';
import {
  Check,
  Eye,
  EyeOff,
  FolderOpen,
  History,
  Image as ImageIcon,
  Layers,
  Link2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Type,
} from 'lucide-react';
import type { Actions, Layer } from './types';
import { flatten } from './types';

const BLENDS = [
  'Normal',
  'Multiply',
  'Screen',
  'Overlay',
  'Soft Light',
  'Hard Light',
  'Darken',
  'Lighten',
  'Color Dodge',
  'Color Burn',
  'Difference',
  'Hue',
  'Saturation',
  'Color',
  'Luminosity',
];

function kindIcon(layer: Layer) {
  if (layer.kind === 'Type') return <Type size={14} />;
  if (layer.kind === 'Adjustment') return <SlidersHorizontal size={14} />;
  if (layer.kind === 'Fill') return <Square size={14} />;
  if (layer.name.startsWith('AI') || layer.name.startsWith('Removed')) return <Sparkles size={14} />;
  return <ImageIcon size={14} />;
}

function describe(layer: Layer) {
  if (layer.text) return `“${layer.text.text}” · ${layer.text.font} ${Math.round(layer.text.sizePt)} pt`;
  if (layer.adjustment) {
    const [name, values] = Object.entries(layer.adjustment)[0] || ['', {}];
    const shown = Object.entries(values || {})
      .filter(
        ([, value]) => typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string',
      )
      .slice(0, 4)
      .map(([key, value]) => `${key} ${typeof value === 'number' ? Math.round(value * 100) / 100 : value}`);
    return [name, ...shown].join(' · ');
  }
  return layer.kind;
}

interface Props extends Actions {
  onGoto: (index: number) => void;
  onDesktop: () => void;
  onSync: () => void;
}

/** Layers with their properties, and the revision history. */
export function Inspector({ document, busy, commands, onGoto, onDesktop, onSync }: Props) {
  const [tab, setTab] = useState<'layers' | 'history'>('layers');
  const layers = document ? flatten(document.state.layers) : [];
  const active = layers.find((layer) => layer.id === document?.state.activeLayer);
  const [name, setName] = useState('');
  useEffect(() => setName(active?.name || ''), [active?.id, document?.revision]);

  function run(command: string, params: object, label: string) {
    commands([{ command, params, label }], label);
  }

  return (
    <aside className="pc-inspector">
      <div className="pc-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'layers'}
          className={tab === 'layers' ? 'active' : ''}
          onClick={() => setTab('layers')}
        >
          <Layers size={14} />
          Layers
        </button>
        <button
          role="tab"
          aria-selected={tab === 'history'}
          className={tab === 'history' ? 'active' : ''}
          onClick={() => setTab('history')}
        >
          <History size={14} />
          History
        </button>
      </div>
      {tab === 'layers' ? (
        <>
          <div className="pc-layer-list">
            {document ? (
              layers.map((layer) => (
                <div
                  key={layer.id}
                  className={`pc-layer ${layer.id === document.state.activeLayer ? 'active' : ''} ${layer.visible ? '' : 'hidden'}`}
                  style={{ paddingLeft: 6 + layer.depth * 14 }}
                >
                  <button
                    className="icon-button"
                    disabled={busy}
                    aria-label={`${layer.visible ? 'Hide' : 'Show'} ${layer.name}`}
                    onClick={() =>
                      run(
                        'layer.setProps',
                        { layer: layer.id, visible: !layer.visible },
                        `${layer.visible ? 'Hide' : 'Show'} ${layer.name}`,
                      )
                    }
                  >
                    {layer.visible ? <Eye size={14} /> : <EyeOff size={14} />}
                  </button>
                  <button
                    className="pc-layer-name"
                    disabled={busy}
                    onClick={() => run('layer.select', { layer: layer.id }, `Select ${layer.name}`)}
                  >
                    <span className="pc-layer-kind">{kindIcon(layer)}</span>
                    <span>
                      <strong>{layer.name}</strong>
                      <small>
                        {layer.kind}
                        {layer.hasMask ? ' · mask' : ''}
                        {layer.smartFilters?.length
                          ? ` · ${layer.smartFilters.length} filter${layer.smartFilters.length > 1 ? 's' : ''}`
                          : ''}
                        {layer.opacity < 1 ? ` · ${Math.round(layer.opacity * 100)}%` : ''}
                      </small>
                    </span>
                    {layer.clipped && <Link2 size={12} aria-label="Clipped" />}
                  </button>
                </div>
              ))
            ) : (
              <div className="pc-inspector-empty">
                <Layers size={24} />
                <p>Your layers will appear here.</p>
                <small>Every edit gets its own named layer, so you can hide, fade or delete it later.</small>
              </div>
            )}
          </div>
          {active && (
            <div className="pc-properties">
              <span className="eyebrow">SELECTED LAYER</span>
              <p className="pc-muted">{describe(active)}</p>
              <label className="field-label">
                Name
                <input
                  value={name}
                  disabled={busy}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && name.trim() && name !== active.name)
                      run(
                        'layer.renameLayer',
                        { layer: active.id, name: name.trim() },
                        `Rename to ${name.trim()}`,
                      );
                  }}
                  onBlur={() => {
                    if (name.trim() && name !== active.name)
                      run(
                        'layer.renameLayer',
                        { layer: active.id, name: name.trim() },
                        `Rename to ${name.trim()}`,
                      );
                  }}
                />
              </label>
              <label className="pc-slider">
                <span>
                  Opacity
                  <output>{Math.round(active.opacity * 100)}%</output>
                </span>
                <input
                  key={`${document?.revision}-${active.id}`}
                  aria-label="Layer opacity"
                  type="range"
                  min={0}
                  max={100}
                  defaultValue={Math.round(active.opacity * 100)}
                  disabled={busy}
                  onPointerUp={(event) =>
                    run(
                      'layer.setProps',
                      { layer: active.id, opacity: Number(event.currentTarget.value) / 100 },
                      'Change layer opacity',
                    )
                  }
                  onKeyUp={(event) => {
                    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
                      run(
                        'layer.setProps',
                        { layer: active.id, opacity: Number(event.currentTarget.value) / 100 },
                        'Change layer opacity',
                      );
                  }}
                />
              </label>
              <label className="field-label">
                Blend mode
                <select
                  value={active.blend || 'Normal'}
                  disabled={busy}
                  onChange={(event) =>
                    run(
                      'layer.setProps',
                      { layer: active.id, blend: event.target.value },
                      `Blend ${event.target.value}`,
                    )
                  }
                >
                  {BLENDS.map((blend) => (
                    <option key={blend}>{blend}</option>
                  ))}
                </select>
              </label>
              {!!active.smartFilters?.length && (
                <div className="pc-filters">
                  <span className="field-label">Smart filters</span>
                  {active.smartFilters.map((filter, index) => (
                    <label key={index} className="pc-check">
                      <input
                        type="checkbox"
                        checked={filter.visible}
                        disabled={busy}
                        onChange={(event) =>
                          run(
                            'layer.smartFilter.setVisible',
                            { layer: active.id, index, visible: event.target.checked },
                            'Toggle smart filter',
                          )
                        }
                      />
                      {filter.command
                        .split('.')
                        .pop()
                        ?.replace(/([A-Z])/g, ' $1')}
                    </label>
                  ))}
                </div>
              )}
              <button
                className="button pc-danger"
                disabled={busy || layers.length < 2}
                onClick={() => {
                  if (window.confirm(`Delete the layer “${active.name}”? You can undo this.`))
                    run('layer.delete', { layer: active.id }, `Delete ${active.name}`);
                }}
              >
                <Trash2 size={14} />
                Delete layer
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="pc-history">
          {document ? (
            document.history.map((entry, index) => (
              <button
                key={entry.id}
                disabled={busy || index === document.cursor}
                className={index === document.cursor ? 'active' : index > document.cursor ? 'future' : ''}
                onClick={() => onGoto(index)}
              >
                <span>{index + 1}</span>
                <span>
                  <strong>{entry.label}</strong>
                  <small>{new Date(entry.created * 1000).toLocaleTimeString()}</small>
                </span>
                {index === document.cursor && <Check size={14} />}
              </button>
            ))
          ) : (
            <p className="pc-muted">Your revisions will appear here. Click one to return to it.</p>
          )}
        </div>
      )}
      <div className="pc-desktop">
        <span className="eyebrow">CONTINUE IN PHOTOCRAFT</span>
        <p>Open a native copy for hands-on painting. Save it there, then bring the changes back.</p>
        <div>
          <button className="button" disabled={!document || busy} onClick={onDesktop}>
            <FolderOpen size={14} />
            Open desktop
          </button>
          {document?.desktop && (
            <button className="button" disabled={busy} onClick={onSync}>
              Sync saved changes
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
