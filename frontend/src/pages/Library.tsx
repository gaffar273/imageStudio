import { useMemo, useState } from 'react';
import { ArrowDownWideNarrow, FolderHeart, Search, Sparkles } from 'lucide-react';
import type { StudioImage } from '../lib/types';
import { ImageCard } from '../components/Workspace';
export function Library({
  images,
  favorites,
  onFavorite,
  onSelect,
  semantic,
  onReset,
  searching,
}: {
  images: StudioImage[];
  favorites: string[];
  onFavorite: (name: string) => void;
  onSelect: (image: StudioImage) => void;
  semantic: (query: string) => void;
  onReset: () => void;
  searching: boolean;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [oldest, setOldest] = useState(false);
  const visible = useMemo(
    () =>
      [...images]
        .filter(
          (image) =>
            (filter !== 'favorites' || favorites.includes(image.name)) &&
            (!query ||
              `${image.metadata.prompt} ${image.metadata.request}`
                .toLowerCase()
                .includes(query.toLowerCase())),
        )
        .sort((a, b) => (oldest ? a.created - b.created : b.created - a.created)),
    [images, favorites, filter, query, oldest],
  );
  return (
    <div className="page-content library-page">
      <div className="page-intro">
        <span className="eyebrow">A COLLECTION OF POSSIBILITIES</span>
        <h2>Made by your imagination.</h2>
        <p>Every experiment, happy accident, and beautiful idea. Right here.</p>
      </div>
      <div className="library-toolbar">
        <div className="library-tabs">
          <button
            className={filter === 'all' ? 'selected' : ''}
            onClick={() => {
              setFilter('all');
              onReset();
            }}
          >
            All creations <span>{images.length}</span>
          </button>
          <button className={filter === 'favorites' ? 'selected' : ''} onClick={() => setFilter('favorites')}>
            <FolderHeart size={15} />
            Favorites <span>{favorites.length}</span>
          </button>
        </div>
        <div className="library-search">
          <Search size={16} />
          <input
            aria-label="Search saved prompts"
            placeholder="Search your creations…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button
          className="button"
          disabled={!query.trim() || searching}
          onClick={() => {
            semantic(query);
            setQuery('');
          }}
        >
          <Sparkles size={15} />
          {searching ? 'Searching…' : 'Visual search'}
        </button>
        <button
          className="icon-button"
          aria-label={oldest ? 'Sort newest first' : 'Sort oldest first'}
          title={oldest ? 'Oldest first' : 'Newest first'}
          onClick={() => setOldest(!oldest)}
        >
          <ArrowDownWideNarrow size={18} />
        </button>
      </div>
      <div className="library-grid">
        {visible.map((image) => (
          <ImageCard
            key={image.name}
            image={image}
            onSelect={() => onSelect(image)}
            favorite={favorites.includes(image.name)}
            onFavorite={() => onFavorite(image.name)}
          />
        ))}
      </div>
      {!visible.length && (
        <div className="page-empty">
          <Search size={32} />
          <h3>No creations here yet.</h3>
          <p>
            {query
              ? 'Try a different word or use visual search.'
              : filter === 'favorites'
                ? 'Tap the heart on an image to save it here.'
                : 'Create your first image to begin your collection.'}
          </p>
        </div>
      )}
    </div>
  );
}
