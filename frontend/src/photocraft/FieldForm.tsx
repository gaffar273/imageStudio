import { useEffect, useState } from 'react';
import type { Field, Layer } from './types';
import { flatten } from './types';

interface Props {
  fields: Field[];
  layers: Layer[];
  /** Called with only the settings the person changed; the engine keeps its defaults for the rest. */
  onChange: (values: Record<string, unknown>) => void;
  resetKey: string;
}

function label(name: string) {
  return name.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, (c) => c.toUpperCase());
}

/** Controls drawn from a PhotoCraft parameter specification: sliders, choices, switches, colors. */
export function FieldForm({ fields, layers, onChange, resetKey }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    setValues({});
    setErrors({});
    onChange({});
  }, [resetKey]);

  function set(name: string, value: unknown) {
    const next = { ...values };
    if (value === undefined) delete next[name];
    else next[name] = value;
    setValues(next);
    onChange(next);
  }

  const visible = fields.filter((field) => field.name !== 'path' && field.name !== 'file');
  if (!visible.length) return <p className="pc-muted">This command has no settings.</p>;
  return (
    <div className="pc-fields">
      {visible.map((field) => {
        const id = `pc-field-${field.name}`;
        const current = values[field.name];
        const title = (
          <span className="pc-field-title">
            {label(field.name)}
            {field.note && <small title={field.note}>{field.note}</small>}
          </span>
        );
        if (field.type === 'number' && field.min != null && field.max != null) {
          const step = field.integer ? 1 : Math.max((field.max - field.min) / 200, 0.01);
          const shown = (current as number | undefined) ?? (field.default as number | undefined) ?? field.min;
          return (
            <label key={field.name} className="pc-slider" htmlFor={id}>
              <span>
                {title}
                <output className={current === undefined ? 'pc-default' : ''}>
                  {Number(shown.toFixed(field.integer ? 0 : 2))}
                </output>
              </span>
              <input
                id={id}
                type="range"
                min={field.min}
                max={field.max}
                step={step}
                value={shown}
                onChange={(event) => set(field.name, Number(event.target.value))}
              />
            </label>
          );
        }
        if (field.type === 'number') {
          return (
            <label key={field.name} className="field-label" htmlFor={id}>
              {title}
              <input
                id={id}
                type="number"
                placeholder={field.default !== undefined ? String(field.default) : ''}
                value={(current as number | undefined) ?? ''}
                onChange={(event) =>
                  set(field.name, event.target.value === '' ? undefined : Number(event.target.value))
                }
              />
            </label>
          );
        }
        if (field.type === 'choice') {
          return (
            <label key={field.name} className="field-label" htmlFor={id}>
              {title}
              <select
                id={id}
                value={(current as string | undefined) ?? ''}
                onChange={(event) => set(field.name, event.target.value || undefined)}
              >
                <option value="">{field.default ? `Default (${field.default})` : 'Default'}</option>
                {field.options?.map((option) => (
                  <option key={option} value={option}>
                    {label(option)}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        if (field.type === 'bool') {
          const checked = (current as boolean | undefined) ?? (field.default as boolean | undefined) ?? false;
          return (
            <label key={field.name} className="pc-check" htmlFor={id}>
              <input
                id={id}
                type="checkbox"
                checked={checked}
                onChange={(e) => set(field.name, e.target.checked)}
              />
              {title}
            </label>
          );
        }
        if (field.type === 'color') {
          return (
            <label key={field.name} className="pc-color" htmlFor={id}>
              {title}
              <span>
                <input
                  id={id}
                  type="color"
                  value={
                    (current as string | undefined) ?? (field.default as string | undefined) ?? '#ffffff'
                  }
                  onChange={(event) => set(field.name, event.target.value)}
                />
                {current !== undefined && (
                  <button type="button" className="text-button" onClick={() => set(field.name, undefined)}>
                    Default
                  </button>
                )}
              </span>
            </label>
          );
        }
        if (field.type === 'layer') {
          return (
            <label key={field.name} className="field-label" htmlFor={id}>
              {title}
              <select
                id={id}
                value={(current as number | undefined) ?? ''}
                onChange={(event) =>
                  set(field.name, event.target.value ? Number(event.target.value) : undefined)
                }
              >
                <option value="">Active layer</option>
                {flatten(layers).map((layer) => (
                  <option key={layer.id} value={layer.id}>
                    {'  '.repeat(layer.depth)}
                    {layer.name}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        return (
          <label key={field.name} className="field-label" htmlFor={id}>
            {title}
            {field.type === 'text' ? (
              <input
                id={id}
                value={(current as string) ?? ''}
                onChange={(e) => set(field.name, e.target.value || undefined)}
              />
            ) : (
              <>
                <textarea
                  id={id}
                  rows={2}
                  spellCheck={false}
                  placeholder="JSON value"
                  onChange={(event) => {
                    const text = event.target.value.trim();
                    if (!text) {
                      setErrors({ ...errors, [field.name]: '' });
                      set(field.name, undefined);
                      return;
                    }
                    try {
                      set(field.name, JSON.parse(text));
                      setErrors({ ...errors, [field.name]: '' });
                    } catch {
                      setErrors({ ...errors, [field.name]: 'Not valid JSON yet' });
                    }
                  }}
                />
                {errors[field.name] && <small className="pc-error">{errors[field.name]}</small>}
              </>
            )}
          </label>
        );
      })}
    </div>
  );
}
