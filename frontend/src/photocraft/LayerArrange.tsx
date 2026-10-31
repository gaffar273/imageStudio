import { useEffect, useRef, useState, type RefObject, type PointerEvent } from 'react';

export interface ArrangeLayer {
  id: number | string; bounds?: number[] | null; visible?: boolean; kind?: string; locked?: boolean;
}
export interface TransformValues { dx: number; dy: number; scaleX: number; scaleY: number }
type Drag = TransformValues & { id: number | string; rect: number[]; start: [number, number]; corner: number | null; pending?: boolean };

export function LayerArrange({ frame, width, height, layers, active, revision, busy, preview, onSelect, onTransform, onDrawing }: {
  frame: RefObject<HTMLDivElement | null>; width: number; height: number; layers: ArrangeLayer[];
  active: number | string | null; revision: string | number; busy: boolean;
  preview: (id: number | string, part: string) => string;
  onSelect: (id: number | string) => void; onTransform: (id: number | string, values: TransformValues) => void;
  onDrawing: (value: boolean) => void;
}) {
  const gesture = useRef<Drag | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [ready, setReady] = useState(false);
  const selected = drag?.id ?? active;
  const layer = layers.find((item) => item.id === selected);
  const bounds = drag?.rect || layer?.bounds;
  const urls = selected === null ? [] : ['below', 'image', 'above'].map((part) => preview(selected, part));
  useEffect(() => { gesture.current = null; setDrag(null); }, [revision]);
  useEffect(() => { if (!busy) setDrag((current) => current?.pending ? null : current); }, [busy]);
  useEffect(() => {
    let stopped = false;
    setReady(false);
    if (urls.length) Promise.all(urls.map((url) => new Promise<void>((resolve, reject) => {
      const image = new Image(); image.onload = () => resolve(); image.onerror = reject; image.src = url;
    }))).then(() => { if (!stopped) setReady(true); }).catch(() => {});
    return () => { stopped = true; };
  }, [selected, revision, urls.join('|')]);

  function point(event: PointerEvent): [number, number] {
    const rect = frame.current!.getBoundingClientRect();
    return [(event.clientX - rect.left) * width / rect.width, (event.clientY - rect.top) * height / rect.height];
  }
  function start(event: PointerEvent<HTMLDivElement>, corner: number | null = null) {
    if (busy || event.button !== 0) return;
    const at = point(event);
    const hit = corner === null ? layers.find((item) => item.visible !== false && item.bounds &&
      ['Pixel', 'Smart Object', 'Type', 'Fill'].includes(item.kind || '') && at[0] >= item.bounds[0] &&
      at[1] >= item.bounds[1] && at[0] <= item.bounds[0] + item.bounds[2] && at[1] <= item.bounds[1] + item.bounds[3]) : layer;
    if (!hit?.bounds || hit.locked) return;
    event.preventDefault(); event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId);
    const current: Drag = { id: hit.id, rect: hit.bounds, start: at, corner, dx: 0, dy: 0, scaleX: 100, scaleY: 100 };
    gesture.current = current; setDrag(current); onDrawing(true);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const current = gesture.current;
    if (!current) return;
    const at = point(event);
    const [x, y, w, h] = current.rect;
    if (current.corner === null) {
      current.dx = Math.max(-16384, Math.min(16384, at[0] - current.start[0]));
      current.dy = Math.max(-16384, Math.min(16384, at[1] - current.start[1]));
    } else {
      const corner = current.corner;
      const anchor = [[x + w, y + h], [x, y + h], [x, y], [x + w, y]][corner]!;
      const factor = Math.max(0.01, Math.min(10, Math.max(Math.abs(at[0] - anchor[0]!) / w!, Math.abs(at[1] - anchor[1]!) / h!)));
      const left = [0, 3].includes(corner) ? anchor[0]! - w! * factor : anchor[0]!;
      const top = [0, 1].includes(corner) ? anchor[1]! - h! * factor : anchor[1]!;
      current.dx = left + w! * factor / 2 - (x! + w! / 2);
      current.dy = top + h! * factor / 2 - (y! + h! / 2);
      current.scaleX = current.scaleY = factor * 100;
    }
    setDrag({ ...current });
  }
  function finish(event: PointerEvent<HTMLDivElement>, cancel = false) {
    const current = gesture.current;
    if (!current) return;
    gesture.current = null; onDrawing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!cancel && Math.abs(current.dx) + Math.abs(current.dy) + Math.abs(current.scaleX - 100) > 0.2) {
      setDrag({ ...current, pending: true });
      onTransform(current.id, { dx: current.dx, dy: current.dy, scaleX: current.scaleX, scaleY: current.scaleY });
    } else { setDrag(null); if (!cancel && current.id !== active) onSelect(current.id); }
  }
  const [x, y, w, h] = bounds || [0, 0, 0, 0];
  const factor = (drag?.scaleX || 100) / 100;
  const left = x! + w! / 2 + (drag?.dx || 0) - w! * factor / 2;
  const top = y! + h! / 2 + (drag?.dy || 0) - h! * factor / 2;
  return <div style={{ position: 'absolute', inset: 0, zIndex: 6, touchAction: 'none', cursor: busy ? 'wait' : 'move' }}
    onPointerDown={(event) => start(event, (event.target as HTMLElement).dataset.corner === undefined ? null : Number((event.target as HTMLElement).dataset.corner))}
    onPointerMove={move} onPointerUp={(event) => finish(event)} onPointerCancel={(event) => finish(event, true)}>
    {drag && ready && <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
      <img src={urls[0]} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
      <img src={urls[1]} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%',
        transformOrigin: `${(x! + w! / 2) * 100 / width}% ${(y! + h! / 2) * 100 / height}%`,
        transform: `translate(${drag.dx * 100 / width}%,${drag.dy * 100 / height}%) scale(${factor})` }} />
      <img src={urls[2]} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
    </div>}
    {bounds && w! > 0 && h! > 0 && <div className="project-layer-outline" style={{ left: `${left * 100 / width}%`, top: `${top * 100 / height}%`,
      width: `${w! * factor * 100 / width}%`, height: `${h! * factor * 100 / height}%` }}>
      {[[0, 0], [100, 0], [100, 100], [0, 100]].map(([px, py], corner) =>
        <button key={corner} data-corner={corner} className="project-layer-handle" aria-label={`Resize image corner ${corner + 1}`}
          style={{ left: `${px}%`, top: `${py}%`, transform: 'translate(-50%,-50%)' }} disabled={busy} />)}
    </div>}
  </div>;
}
