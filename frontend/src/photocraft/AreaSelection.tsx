import { useEffect, useRef, useState } from 'react';
import type { AreaMark, AreaTool } from './types';

interface Props {
  width: number;
  height: number;
  marks: AreaMark[];
  tool: AreaTool | null;
  size: number;
  onChange: (marks: AreaMark[]) => void;
  onDrawing: (drawing: boolean) => void;
}

/** Normalized coordinates keep the marked pixels aligned at every zoom level. */
export function AreaSelection({ width, height, marks, tool, size, onChange, onDrawing }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const draft = useRef<AreaMark | null>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const scale = Math.min(1, 1600 / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));

  function render() {
    const ctx = canvas.current?.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    for (const mark of [...marks, ...(draft.current ? [draft.current] : [])]) {
      ctx.globalCompositeOperation = mark.tool === 'erase' ? 'destination-out' : 'source-over';
      ctx.fillStyle = ctx.strokeStyle = '#c4f477';
      ctx.lineWidth = mark.size * w;
      ctx.lineCap = ctx.lineJoin = 'round';
      ctx.beginPath();
      mark.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)));
      if (mark.tool === 'lasso') {
        ctx.closePath();
        ctx.fill('evenodd');
      } else {
        ctx.stroke();
        const [x, y] = mark.points[0];
        ctx.beginPath();
        ctx.arc(x * w, y * h, (mark.size * w) / 2, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  useEffect(render, [marks, w, h]);
  useEffect(() => () => onDrawing(false), []);

  function point(event: React.PointerEvent<HTMLCanvasElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  }

  function finish(commit: boolean) {
    const mark = draft.current;
    draft.current = null;
    onDrawing(false);
    if (commit && mark && (mark.tool !== 'lasso' || mark.points.length >= 3)) onChange([...marks, mark]);
    else render();
  }

  return (
    <>
      <canvas
        ref={canvas}
        className={`pc-area-overlay ${tool ? 'drawing' : ''}`}
        width={w}
        height={h}
        aria-label="Mark the edit area on the photo"
        onPointerDown={(event) => {
          if (!tool || !event.isPrimary || draft.current || event.button !== 0 || marks.length >= 100) return;
          event.preventDefault();
          event.stopPropagation();
          event.currentTarget.setPointerCapture(event.pointerId);
          draft.current = { tool, size, points: [point(event)] };
          onDrawing(true);
          render();
        }}
        onPointerMove={(event) => {
          if (!event.isPrimary) return;
          const next = point(event);
          setCursor(next);
          if (!draft.current) return;
          const points = draft.current.points;
          const previous = points[points.length - 1];
          if (
            points.length < 2000 &&
            Math.hypot((next[0] - previous[0]) * w, (next[1] - previous[1]) * h) >= 1
          ) {
            points.push(next);
            render();
          }
        }}
        onPointerUp={(event) => {
          if (!draft.current) return;
          finish(true);
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => finish(false)}
        onLostPointerCapture={() => {
          if (draft.current) finish(false);
        }}
        onPointerLeave={() => setCursor(null)}
      />
      {tool && tool !== 'lasso' && cursor && (
        <span
          className="pc-area-cursor"
          style={{
            left: `${cursor[0] * 100}%`,
            top: `${cursor[1] * 100}%`,
            width: `${size * 100}%`,
            aspectRatio: '1',
          }}
        />
      )}
    </>
  );
}
