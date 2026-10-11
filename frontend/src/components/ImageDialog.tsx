import { useEffect, useRef } from 'react';
import { ArrowDownToLine, Copy, Heart, ImagePlus, Search, SquarePen, X } from 'lucide-react';
import type { StudioImage } from '../lib/types';
export function ImageDialog({
  image,
  close,
  reuse,
  edit,
  krita,
  similar,
  favorite,
  onFavorite,
}: {
  image: StudioImage;
  close: () => void;
  reuse: () => void;
  edit: () => void;
  krita: () => void;
  similar: () => void;
  favorite: boolean;
  onFavorite: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  const meta = image.metadata;
  return (
    <dialog
      ref={ref}
      className="image-dialog"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="dialog-layout">
        <div className="dialog-image">
          <img src={image.url} alt={meta.prompt || 'Saved image'} />
        </div>
        <div className="dialog-info">
          <div className="dialog-heading">
            <span className="eyebrow">YOUR CREATION</span>
            <button autoFocus className="icon-button" aria-label="Close image details" onClick={close}>
              <X size={20} />
            </button>
          </div>
          <h2>A moment, made real.</h2>
          <p className="dialog-date">
            {new Date(image.created * 1000).toLocaleString(undefined, {
              dateStyle: 'medium',
              timeStyle: 'short',
            })}
          </p>
          <span className="field-label">PROMPT</span>
          <p className="saved-prompt">{meta.request || meta.prompt || 'No prompt saved for this image.'}</p>
          <dl className="metadata-grid">
            <div>
              <dt>Dimensions</dt>
              <dd>
                {meta.width} × {meta.height}
              </dd>
            </div>
            <div>
              <dt>Seed</dt>
              <dd>{meta.seed ?? '—'}</dd>
            </div>
            <div>
              <dt>Steps</dt>
              <dd>{meta.steps ?? '—'}</dd>
            </div>
            <div>
              <dt>Render time</dt>
              <dd>{meta.total_seconds != null ? `${meta.total_seconds}s` : '—'}</dd>
            </div>
            <div>
              <dt>Photo style</dt>
              <dd>{meta.style || 'Original'}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{meta.model?.split('/').pop() || 'Unknown'}</dd>
            </div>
          </dl>
          <div className="dialog-buttons">
            <a className="generate-button" href={`/api/library/${image.name}/download`}>
              <ArrowDownToLine size={16} />
              Download original
            </a>
            {meta.layered_document && (
              <a className="button" href={`/api/photocraft/${image.name}/download`}>
                <ArrowDownToLine size={16} />
                Download PSD
              </a>
            )}
            <button
              className="button"
              disabled={meta.mode === 'edit' || meta.mode === 'krita'}
              onClick={reuse}
            >
              <Copy size={15} />
              Reuse settings
            </button>
            <div>
              <button className="button" onClick={edit}>
                <SquarePen size={15} />
                Edit image
              </button>
              <button className="button" onClick={krita}>
                <ImagePlus size={15} />
                Open in Krita
              </button>
            </div>
            <button className="button" onClick={similar}>
              <Search size={15} />
              Find similar images
            </button>
            <button className={`text-button ${favorite ? 'is-favorite' : ''}`} onClick={onFavorite}>
              <Heart size={15} fill={favorite ? 'currentColor' : 'none'} />
              {favorite ? 'Saved to favorites' : 'Save to favorites'}
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
