import { useCallback, useEffect, useState } from 'react';
import {
  Brain,
  Check,
  Circle,
  Cpu,
  Folder,
  HardDrive,
  LoaderCircle,
  Moon,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import type { Config, Learned } from '../lib/types';
import { api } from '../lib/api';
import { Toggle } from '../components/Controls';
interface Props {
  config: Config;
  notify: (message: string) => void;
  error: (message: string) => void;
  onUseSettings: (profile: Learned['profile']) => void;
}
const modelNames: Record<string, string> = { realistic: 'Realistic', accurate: 'Accurate', turbo: 'Turbo' };
const stepNames: Record<string, string> = { grade: 'light and color looks' };
export function StudioSettings({ config, notify, error, onUseSettings }: Props) {
  const [learned, setLearned] = useState<Learned | null>(null);
  const [phrase, setPhrase] = useState('');
  const [means, setMeans] = useState('');
  const load = useCallback(() => {
    api<Learned>('/memory')
      .then(setLearned)
      .catch(() => setLearned(null));
  }, []);
  useEffect(load, [load]);
  const training = learned?.personal.state === 'training';
  useEffect(() => {
    if (!training) return;
    const id = window.setInterval(load, 4000);
    return () => clearInterval(id);
  }, [training, load]);
  async function change(body: unknown, message?: string) {
    try {
      setLearned(await api<Learned>('/memory', body));
      if (message) notify(message);
      return true;
    } catch (err) {
      error(String(err));
      return false;
    }
  }
  async function train() {
    try {
      await api('/personal-lora', { action: 'train' });
      notify('Learning your style. Rendering is paused until it finishes.');
      load();
    } catch (err) {
      error(String(err));
    }
  }
  async function nightly(enabled: boolean) {
    try {
      await api('/personal-lora', { action: 'nightly', enabled });
      load();
    } catch (err) {
      error(String(err));
    }
  }
  const features = [
    { label: 'Prompt assistant', ready: config.assistant, file: 'Download prompt assistant.bat' },
    { label: 'Photo editing', ready: config.editing, file: 'Download editing model.bat' },
    { label: 'Face and hand repair', ready: config.repair, file: 'Download repair models.bat' },
    { label: 'Visual image search', ready: config.search, file: 'Download image search model.bat' },
    { label: 'Reference face pool', ready: config.references, file: 'Build face pool.bat' },
    { label: 'Realism LoRA', ready: config.lora, file: 'See docs/model-guide.md for training instructions' },
  ];
  const personal = learned?.personal;
  const profile = learned?.profile ?? {};
  const profileText = [
    profile.model && modelNames[profile.model],
    profile.size,
    profile.finish && profile.finish !== 'Off' && `${profile.finish} finish`,
    profile.realism ? `realism ${profile.realism}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <div className="page-content settings-page">
      <div className="page-intro">
        <span className="eyebrow">YOUR OWN CREATIVE ENGINE</span>
        <h2>Everything, close to home.</h2>
        <p>Your models and images live on this computer.</p>
      </div>
      <div className="settings-summary">
        <div>
          <Cpu />
          <h3>Local inference</h3>
          <p>Images are rendered by your own hardware.</p>
        </div>
        <div>
          <ShieldCheck />
          <h3>Private by design</h3>
          <p>Your prompts and creations stay in your workspace.</p>
        </div>
        <div>
          <HardDrive />
          <h3>Your collection</h3>
          <p>Original PNGs and settings are saved in images/.</p>
        </div>
      </div>
      <h3 className="settings-heading">What the studio has learned from you</h3>
      {!learned ? (
        <p className="settings-note">Restart the image generator to turn on learning.</p>
      ) : (
        <>
          <div className="settings-list">
            <div className="learn-row">
              <span className="settings-icon">
                <Brain size={18} />
              </span>
              <div>
                <strong>My style LoRA</strong>
                <small>
                  {training
                    ? personal!.message || 'Learning your style…'
                    : personal!.state === 'failed'
                      ? `Last training failed: ${personal!.message}`
                      : personal!.ready
                        ? `Learned from ${personal!.trained_on} favorites${
                            personal!.trained_at
                              ? ` on ${new Date(personal!.trained_at * 1000).toLocaleDateString()}`
                              : ''
                          }. ${personal!.changed} changed since. Use the "My style" slider in Create.`
                        : personal!.favorites >= personal!.minimum
                          ? `Learns the look of your ${personal!.favorites} favorite pictures, in about ${personal!.minutes} minutes.`
                          : `Learns the look of your favorite pictures. Mark ${personal!.minimum - personal!.favorites} more as favorites to start (${personal!.favorites} of ${personal!.minimum}).`}
                </small>
                {training && (
                  <div className="progress-track">
                    <span style={{ width: `${Math.max(3, personal!.progress * 100)}%` }} />
                  </div>
                )}
              </div>
              <button
                className="button"
                disabled={training || personal!.favorites < personal!.minimum}
                title={`About ${personal!.minutes} minutes; rendering pauses while it learns.`}
                onClick={train}
              >
                {training ? <LoaderCircle size={15} className="spin" /> : <Brain size={15} />}
                {training ? 'Learning…' : personal!.ready ? 'Retrain now' : 'Train now'}
              </button>
            </div>
            <div className="learn-row">
              <span className="settings-icon">
                <Moon size={18} />
              </span>
              <Toggle
                label="Learn overnight"
                description="Between 1 and 5 AM, when the studio is open and idle and at least 5 favorites changed."
                checked={personal!.nightly}
                onChange={nightly}
              />
            </div>
            {profileText && (
              <div className="learn-row">
                <span className="settings-icon">
                  <Check size={18} />
                </span>
                <div>
                  <strong>Your usual settings</strong>
                  <small>
                    Most of your {learned.favorites} favorites: {profileText}
                  </small>
                </div>
                <button className="button" onClick={() => onUseSettings(profile)}>
                  Use these
                </button>
              </div>
            )}
          </div>
          <h3 className="settings-heading">Words you taught me</h3>
          <div className="settings-list">
            {learned.words.map((word) => (
              <div key={word.phrase} className="learn-row">
                <div>
                  <strong>“{word.phrase}”</strong>
                  <small>
                    means “{word.means}” · {word.source === 'correction' ? 'from a correction' : 'taught'} ·
                    used {word.used} time{word.used === 1 ? '' : 's'}
                  </small>
                </div>
                <button
                  className="icon-button"
                  title="Forget"
                  aria-label={`Forget ${word.phrase}`}
                  onClick={() =>
                    change({ action: 'forget', phrase: word.phrase }, `Forgotten: “${word.phrase}”.`)
                  }
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
            <form
              className="learn-form"
              onSubmit={(event) => {
                event.preventDefault();
                change({ action: 'teach', phrase, means }, `Learned: “${phrase}”.`).then((saved) => {
                  if (!saved) return;
                  setPhrase('');
                  setMeans('');
                });
              }}
            >
              <input
                aria-label="Phrase"
                placeholder="When I say… (make it pop)"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
              />
              <input
                aria-label="Meaning"
                placeholder="I mean… (more contrast and vibrance)"
                value={means}
                onChange={(e) => setMeans(e.target.value)}
              />
              <button className="button" disabled={phrase.trim().length < 3 || !means.trim()}>
                Teach
              </button>
            </form>
          </div>
          {Object.keys(learned.strength).length > 0 && (
            <>
              <h3 className="settings-heading">How strong you like edits</h3>
              <div className="settings-list">
                <div className="learn-row">
                  <div>
                    <small>
                      {Object.entries(learned.strength)
                        .map(
                          ([op, factor]) =>
                            `${stepNames[op] ?? op.replace(/_/g, ' ')}: ${Math.round(factor * 100)}% of normal`,
                        )
                        .join(' · ')}
                    </small>
                  </div>
                  <button
                    className="button"
                    onClick={() => change({ action: 'reset_strength' }, 'Edit strengths are back to normal.')}
                  >
                    Reset
                  </button>
                </div>
              </div>
            </>
          )}
          <p className="settings-note">
            In Krita or the Krita tab, type <code>remember: make it pop means more contrast</code>, correct a
            result with <code>no, I meant warmer</code>, or say <code>too much</code> / <code>more</code>{' '}
            right after an edit. <code>forget make it pop</code> and <code>forget everything</code> undo what
            was learned. Everything stays in the work folder on this computer.
          </p>
        </>
      )}
      <h3 className="settings-heading">Generation models</h3>
      <div className="settings-list">
        {config.models.map((model) => (
          <div key={model.id}>
            <span className="settings-icon">
              <Cpu size={18} />
            </span>
            <div>
              <strong>{model.label}</strong>
              <small>
                {model.id === 'realistic'
                  ? 'RealVisXL 5.0'
                  : model.id === 'accurate'
                    ? 'Z-Image Turbo'
                    : 'SDXL Turbo'}
              </small>
            </div>
            <span className={model.ready ? 'ready-label' : 'muted'}>
              {model.ready ? <Check size={14} /> : <Circle size={12} />}{' '}
              {model.ready ? 'Installed' : 'Not installed'}
            </span>
          </div>
        ))}
      </div>
      <h3 className="settings-heading">Creative tools</h3>
      <div className="settings-list">
        {features.map((feature) => (
          <div key={feature.label}>
            <span className="settings-icon">
              <Folder size={18} />
            </span>
            <div>
              <strong>{feature.label}</strong>
              <small>{feature.ready ? 'Ready to use' : `scripts/windows/${feature.file}`}</small>
            </div>
            <span className={feature.ready ? 'ready-label' : 'muted'}>
              {feature.ready ? <Check size={14} /> : <Circle size={12} />}{' '}
              {feature.ready ? 'Available' : 'Setup required'}
            </span>
          </div>
        ))}
      </div>
      <p className="settings-note">
        Model downloads and setup shortcuts are in <code>scripts/windows/</code>. Refresh the studio after
        installing a model.
      </p>
    </div>
  );
}
