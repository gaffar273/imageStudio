import { useRef, useState } from 'react';
import { Layers, Upload } from 'lucide-react';
import type { CraftDocument, Region } from './types';

interface Props {
  document: CraftDocument | null;
  compare: boolean;
  zoom: number;
  regions: Region[];
  highlight: number | null;
  busy: boolean;
  onOpen: () => void;
  onLibrary: () => void;
  onDrop: (file?: File) => void;
}

/** The document preview with a draggable before/after split and the areas a plan will touch. */
export function Canvas({
  document,
  compare,
  zoom,
  regions,
  highlight,
  busy,
  onOpen,
  onLibrary,
  onDrop,
}: Props) {
  const [split, setSplit] = useState(50);
  const frame = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function move(clientX: number) {
    const box = frame.current?.getBoundingClientRect();
    if (box) setSplit(Math.min(100, Math.max(0, ((clientX - box.left) / box.width) * 100)));
  }

  return (
    <div
      className={`pc-canvas ${document ? 'has-document' : ''}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        onDrop(event.dataTransfer.files[0]);
      }}
    >
      {document ? (
        <div
          ref={frame}
          className={`pc-frame ${zoom === 0 ? 'fit' : ''}`}
          style={zoom === 0 ? undefined : { width: `${(document.state.width * zoom) / 100}px` }}
          onPointerDown={(event) => {
            if (!compare) return;
            dragging.current = true;
            event.currentTarget.setPointerCapture(event.pointerId);
            move(event.clientX);
          }}
          onPointerMove={(event) => dragging.current && move(event.clientX)}
          onPointerUp={() => (dragging.current = false)}
        >
          <img
            className="pc-image"
            src={document.preview}
            alt="Current document"
            style={{ aspectRatio: `${document.state.width} / ${document.state.height}` }}
            draggable={false}
          />
          {compare && (
            <>
              <img
                className="pc-before"
                src={document.original}
                alt="Original before editing"
                style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
                draggable={false}
              />
              <div className="pc-split" style={{ left: `${split}%` }}>
                <span />
              </div>
              <div className="pc-compare-labels">
                <span>Original</span>
                <span>Current</span>
              </div>
            </>
          )}
          {!compare &&
            regions.map((region) =>
              region.boxes.map((box, index) => (
                <div
                  key={`${region.requirement}-${index}`}
                  className={`pc-region ${highlight === null || highlight === region.requirement ? 'on' : ''}`}
                  style={{
                    left: `${box[0] * 100}%`,
                    top: `${box[1] * 100}%`,
                    width: `${box[2] * 100}%`,
                    height: `${box[3] * 100}%`,
                  }}
                >
                  {index === 0 && <span>{region.label}</span>}
                </div>
              )),
            )}
        </div>
      ) : (
        <div className="pc-empty">
          <span className="pc-empty-symbol">
            <Layers size={34} strokeWidth={1.3} />
          </span>
          <span className="eyebrow">A PLACE FOR YOUR NEXT GREAT EDIT</span>
          <h2>Bring your image. Keep your possibilities.</h2>
          <p>
            Open a photo or layered document, then describe the edit or use the tools on the left. Every
            change lands on its own layer, and every revision is kept.
          </p>
          <button className="generate-button" disabled={busy} onClick={onOpen}>
            <Upload size={16} />
            Open a document
          </button>
          <button className="text-button" onClick={onLibrary}>
            Choose from your library
          </button>
          <small>PSD · PSB · PCraft · TIFF · PNG · JPEG · WebP · drop a file here</small>
        </div>
      )}
    </div>
  );
}
