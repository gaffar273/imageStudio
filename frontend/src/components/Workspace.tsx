import {
  ArrowDownToLine,
  ArrowUpRight,
  Expand,
  Heart,
  ImageIcon,
  LoaderCircle,
  Sparkles,
  Square,
  WandSparkles,
} from 'lucide-react';
import type { Job, StudioImage } from '../lib/types';
import { ideas } from './PromptPanel';
interface Props {
  images: StudioImage[];
  job: Job | null;
  onCancel: () => void;
  onSelect: (image: StudioImage) => void;
  onLibrary: () => void;
  onPrompt: (prompt: string) => void;
  favorites: string[];
  onFavorite: (name: string) => void;
}
export function ImageCard({
  image,
  onSelect,
  favorite,
  onFavorite,
}: {
  image: StudioImage;
  onSelect: () => void;
  favorite: boolean;
  onFavorite: () => void;
}) {
  const prompt = image.metadata.request || image.metadata.prompt || 'Untitled creation';
  return (
    <article className="image-card">
      <button className="image-card-open" onClick={onSelect} aria-label={`View ${prompt}`}>
        <img loading="lazy" src={image.thumbnail} alt={prompt} />
        <span className="image-card-shade" />
        <span className="image-card-caption">{prompt}</span>
      </button>
      <button
        className={`favorite-button ${favorite ? 'is-favorite' : ''}`}
        title={favorite ? 'Remove from favorites' : 'Add to favorites'}
        onClick={onFavorite}
      >
        <Heart size={15} fill={favorite ? 'currentColor' : 'none'} />
      </button>
      <span className="image-card-size">
        {image.metadata.width || '—'} × {image.metadata.height || '—'}
      </span>
    </article>
  );
}
export function Workspace({
  images,
  job,
  onCancel,
  onSelect,
  onLibrary,
  onPrompt,
  favorites,
  onFavorite,
}: Props) {
  const scenic =
    images.find((image) =>
      /^(a |an )?(wide |cinematic |photograph of |landscape )*(seaside|coast|mountain|landscape|turquoise alpine|cabin|aurora)/i.test(
        image.metadata.prompt || '',
      ),
    ) || images[0];
  const results = job?.images || [];
  return (
    <div className="creative-workspace">
      <div className="canvas-topline">
        <span>
          <span className="tiny-square" />
          Your canvas
        </span>
        <span>
          <i className="dot" />
          Private workspace
        </span>
      </div>
      {job &&
      (job.state === 'running' ||
        results.length > 0 ||
        job.state === 'error' ||
        job.state === 'cancelled') ? (
        <section className="result-canvas">
          {results.length > 0 ? (
            <>
              <img
                className="result-image"
                src={results[results.length - 1].url}
                alt={results[results.length - 1].metadata.prompt || 'Generated image'}
              />
              <div className="result-actions">
                <button className="button" onClick={() => onSelect(results[results.length - 1])}>
                  <Expand size={16} />
                  View details
                </button>
                <a className="button" href={`/api/library/${results[results.length - 1].name}/download`}>
                  <ArrowDownToLine size={16} />
                  Download
                </a>
              </div>
            </>
          ) : (
            <div className="render-placeholder">
              <div className="orbit">
                <Sparkles size={32} />
              </div>
              <h2>
                {job.state === 'running'
                  ? 'A little imagination. A little magic.'
                  : job.state === 'error'
                    ? 'Let’s give that another try.'
                    : 'Paused at your request.'}
              </h2>
              <p>{job.state === 'running' ? 'Your image is taking shape.' : job.message}</p>
            </div>
          )}
          <div className={`job-status ${job.state === 'error' ? 'error-status' : ''}`} role="status">
            <div>
              {job.state === 'running' && <LoaderCircle size={16} className="spin" />}
              <span>{job.message}</span>
              {job.state === 'running' && (
                <button className="text-button" onClick={onCancel}>
                  <Square size={12} />
                  Stop
                </button>
              )}
            </div>
            {job.state === 'running' && (
              <div className="progress-track">
                <span style={{ width: `${Math.max(3, job.progress * 100)}%` }} />
              </div>
            )}
          </div>
          {results.length > 1 && (
            <div className="result-strip">
              {results.map((image) => (
                <button key={image.name} onClick={() => onSelect(image)}>
                  <img src={image.thumbnail} alt={image.metadata.prompt || 'Generated variation'} />
                </button>
              ))}
            </div>
          )}
          {job.understood && (
            <details className="result-notes">
              <summary>Prompt interpretation</summary>
              <p>{job.understood}</p>
              {job.report && <p>{job.report}</p>}
            </details>
          )}
        </section>
      ) : (
        <section className="welcome-canvas">
          {scenic && (
            <img className="welcome-image" src={scenic.url} alt="A landscape from your image library" />
          )}
          <div className="welcome-shade" />
          <span className="canvas-corner top-left" />
          <span className="canvas-corner bottom-right" />
          <div className="welcome-content">
            <span className="eyebrow">
              <span />A SPACE FOR YOUR IMAGINATION
            </span>
            <h2>
              What if you could
              <br />
              make <em>anything?</em>
            </h2>
            <p>
              A passing thought. A faraway place. Something
              <br className="desktop-break" /> that only exists in your head. Start with a few words.
            </p>
            <button onClick={() => onPrompt(ideas[0].prompt)} className="welcome-button">
              Find your first spark
              <ArrowUpRight size={17} />
            </button>
          </div>
          <div className="canvas-footnote">
            <span>
              <Sparkles size={13} />
              From a spark to something beautiful.
            </span>
            <span>YOUR IDEAS, WITHOUT LIMITS</span>
          </div>
        </section>
      )}
      <div className="recent-heading">
        <div>
          <h3>
            Fresh from your imagination <span>{images.length}</span>
          </h3>
          <p>Your latest creations, all in one place.</p>
        </div>
        <button className="text-button" onClick={onLibrary}>
          View library
          <ArrowUpRight size={15} />
        </button>
      </div>
      {images.length ? (
        <div className="recent-grid">
          {images.slice(0, 4).map((image) => (
            <ImageCard
              key={image.name}
              image={image}
              onSelect={() => onSelect(image)}
              favorite={favorites.includes(image.name)}
              onFavorite={() => onFavorite(image.name)}
            />
          ))}
        </div>
      ) : (
        <div className="empty-library">
          <ImageIcon size={24} />
          <p>Your first creation belongs here.</p>
        </div>
      )}
      <div className="workspace-tip">
        <WandSparkles size={15} />
        <span>A little detail goes a long way. Try describing the light, the mood, or the moment.</span>
        <span>✧</span>
      </div>
    </div>
  );
}
