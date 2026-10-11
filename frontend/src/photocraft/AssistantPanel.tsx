import { useState } from 'react';
import {
  AlertTriangle,
  Brush,
  Eraser,
  Lasso,
  Undo2,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Info,
  LoaderCircle,
  Lock,
  Ruler,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import type { AreaTool, CraftDocument, Plan, Revision } from './types';

const EXAMPLES = [
  'Professional polish',
  'Crop to 4:5 keeping the subject in frame, warm it slightly and add “SUMMER” at the top in white',
  'Blur the background, brighten the subject a little and add a subtle vignette',
  'Make the sky dramatic, deepen the blues and remove the small object on the left',
  'Cut out the subject and put it on a pastel pink background',
];

const TARGET_WORDS: Record<string, string> = {
  'whole image': 'Whole image',
  'main subject': 'Subject',
  background: 'Background',
  sky: 'Sky',
  color: 'Color range',
  shadows: 'Shadows',
  midtones: 'Midtones',
  highlights: 'Highlights',
  area: 'Area',
  layer: 'Layer',
};

interface Props {
  document: CraftDocument | null;
  busy: boolean;
  brain: boolean;
  plan: Plan | null;
  onPlan: (prompt: string) => void;
  onApply: (partial: boolean) => void;
  onDiscard: () => void;
  onHighlight: (requirement: number | null) => void;
  areaEnabled: boolean;
  areaAvailable: boolean;
  areaTool: AreaTool;
  markCount: number;
  brushSize: number;
  onAreaEnabled: (enabled: boolean) => void;
  onAreaTool: (tool: AreaTool) => void;
  onBrushSize: (size: number) => void;
  onUndoMark: () => void;
  onClearMarks: () => void;
}

function ResultCheck({ revision }: { revision: Revision }) {
  const checks = revision.checks || [];
  const review = revision.review || [];
  if (!checks.length && !review.length && !revision.notes?.length) return null;
  const failed =
    checks.filter((check) => !check.passed).length + review.filter((v) => v.verdict === 'not done').length;
  return (
    <section className="pc-result">
      <div className="pc-section-head">
        <span className="eyebrow">RESULT CHECK</span>
        <strong className={failed ? 'warn' : 'ok'}>
          {failed ? `${failed} item${failed > 1 ? 's' : ''} to look at` : 'Everything checked out'}
        </strong>
      </div>
      {checks.length > 0 && (
        <ul className="pc-checks">
          {checks.map((check, index) => (
            <li key={index} className={check.passed ? 'pass' : 'fail'}>
              {check.passed ? <Check size={13} /> : <X size={13} />}
              <span>{check.check}</span>
              <Ruler size={11} aria-label="Measured" />
            </li>
          ))}
        </ul>
      )}
      {review.length > 0 && (
        <>
          <small className="pc-muted">AI visual review (can be wrong; measured checks above are exact)</small>
          <ul className="pc-checks">
            {review.map((verdict, index) => (
              <li
                key={index}
                className={
                  verdict.verdict === 'done' ? 'pass' : verdict.verdict === 'not done' ? 'fail' : 'maybe'
                }
              >
                {verdict.verdict === 'done' ? (
                  <Check size={13} />
                ) : verdict.verdict === 'not done' ? (
                  <X size={13} />
                ) : (
                  <CircleHelp size={13} />
                )}
                <span>
                  <b>
                    {verdict.item ||
                      (verdict.requirement !== null && revision.requirements?.[verdict.requirement])}
                  </b>
                  {verdict.note}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {revision.notes?.map((note, index) => (
        <p key={index} className="pc-note">
          <Info size={13} />
          {note}
        </p>
      ))}
    </section>
  );
}

/** Describe an edit in words, review how it was understood, then apply it. */
export function AssistantPanel({
  document,
  busy,
  brain,
  plan,
  onPlan,
  onApply,
  onDiscard,
  onHighlight,
  areaEnabled,
  areaAvailable,
  areaTool,
  markCount,
  brushSize,
  onAreaEnabled,
  onAreaTool,
  onBrushSize,
  onUndoMark,
  onClearMarks,
}: Props) {
  const [prompt, setPrompt] = useState('');
  const [showSteps, setShowSteps] = useState(false);
  const revision = document?.history[document.cursor];
  const stale = plan && plan.revision !== document?.revision;
  const blocking = plan?.unresolved.length || 0;

  return (
    <div className="pc-panel-body">
      <div className="pc-panel-intro">
        <h2>Describe your edit</h2>
        <p>Say what to change, where, and how much. Name what must stay untouched. Every detail is read.</p>
      </div>
      <section className="pc-area-controls" aria-label="Edit area">
        <span className="eyebrow">APPLY PROMPT TO</span>
        <div className="pc-area-buttons">
          <button disabled={busy} aria-pressed={!areaEnabled} onClick={() => onAreaEnabled(false)}>
            Whole image
          </button>
          <button
            disabled={busy || !document || !areaAvailable}
            aria-pressed={areaEnabled}
            onClick={() => onAreaEnabled(true)}
          >
            <Lasso size={14} /> Mark an area
          </button>
        </div>
        {!areaAvailable && (
          <small>Restart the studio after the current edit finishes to enable area marking.</small>
        )}
        {areaEnabled && (
          <>
            <div className="pc-area-buttons" role="group" aria-label="Marking tools">
              {(
                [
                  { id: 'brush', label: 'Brush', icon: Brush },
                  { id: 'lasso', label: 'Lasso', icon: Lasso },
                  { id: 'erase', label: 'Erase', icon: Eraser },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  disabled={busy}
                  aria-pressed={areaTool === id}
                  onClick={() => onAreaTool(id)}
                >
                  <Icon size={14} />
                  {label}
                </button>
              ))}
            </div>
            {areaTool !== 'lasso' && (
              <label className="pc-area-size">
                Brush size{' '}
                <input
                  aria-label="Area brush size"
                  type="range"
                  min="0.003"
                  max="0.15"
                  step="0.001"
                  value={brushSize}
                  disabled={busy}
                  onChange={(event) => onBrushSize(Number(event.target.value))}
                />
              </label>
            )}
            <p>
              {areaTool === 'lasso'
                ? 'Draw a closed loop around each spot.'
                : 'Paint over the spots you want to change.'}{' '}
              You can mark several spots. Only the green area will be edited.
            </p>
            <div className="pc-area-buttons">
              <button disabled={busy || !markCount} onClick={onUndoMark}>
                <Undo2 size={13} />
                Undo mark
              </button>
              <button disabled={busy || !markCount} onClick={onClearMarks}>
                Clear marks
              </button>
            </div>
            <small role="status">
              {markCount ? 'Marked area only · outside protected' : 'Mark the photo before planning.'}
            </small>
          </>
        )}
      </section>
      <label className="pc-prompt">
        <textarea
          aria-label="PhotoCraft instructions"
          value={prompt}
          rows={5}
          placeholder="Warm only the sky a little, blur the background, add “SUMMER” at the top in white at 48 pt, then crop to 4:5. Keep the person unchanged."
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (
              (event.ctrlKey || event.metaKey) &&
              event.key === 'Enter' &&
              prompt.trim() &&
              document &&
              !busy &&
              (!areaEnabled || markCount > 0)
            )
              onPlan(prompt);
          }}
        />
        <span className="pc-prompt-foot">
          <small>
            {brain ? 'Local vision planner · Ctrl+Enter' : 'Planner not installed · presets only'}
          </small>
          <button
            className="pc-send"
            disabled={!document || busy || !prompt.trim() || (areaEnabled && !markCount)}
            onClick={() => onPlan(prompt)}
          >
            {busy ? <LoaderCircle size={15} className="spin" /> : <Send size={15} />}
            Plan
          </button>
        </span>
      </label>
      {!plan && (
        <div className="pc-examples">
          <span className="eyebrow">TRY</span>
          {EXAMPLES.map((text) => (
            <button key={text} onClick={() => setPrompt(text)}>
              {text}
              <ChevronRight size={12} />
            </button>
          ))}
        </div>
      )}
      {plan && (
        <section className="pc-plan" onMouseLeave={() => onHighlight(null)}>
          <div className="pc-section-head">
            <span className="eyebrow">
              I UNDERSTOOD {plan.edits.length || plan.steps.length} CHANGE
              {(plan.edits.length || plan.steps.length) === 1 ? '' : 'S'}
            </span>
            <button className="text-button" onClick={onDiscard}>
              Discard
            </button>
          </div>
          <ol className="pc-edit-cards">
            {plan.edits.map((edit, index) => (
              <li key={index} onMouseEnter={() => onHighlight(index)}>
                <span className="pc-edit-number">{index + 1}</span>
                <div>
                  <q>{edit.quote}</q>
                  <p>{edit.explain}</p>
                  <span className="pc-chips">
                    <span>{edit.action?.replace(/_/g, ' ')}</span>
                    {edit.target && edit.target !== 'whole image' && (
                      <span>{edit.object || TARGET_WORDS[edit.target] || edit.target}</span>
                    )}
                    {edit.value !== null && edit.value !== undefined && <span>{edit.value}</span>}
                    {edit.value == null && edit.strength && edit.strength !== 'moderate' && (
                      <span>{edit.strength}</span>
                    )}
                    {edit.color && <span>{edit.color}</span>}
                    {edit.position && <span>{edit.position}</span>}
                  </span>
                </div>
              </li>
            ))}
          </ol>
          {plan.preserve.length > 0 && (
            <div className="pc-preserve">
              <Lock size={13} />
              <div>
                <strong>Kept unchanged</strong>
                {plan.preserve.map((item, index) => (
                  <p key={index}>{item}</p>
                ))}
              </div>
            </div>
          )}
          {[...plan.questions, ...plan.notes].map((note, index) => (
            <p key={index} className="pc-note">
              <Info size={13} />
              {note}
            </p>
          ))}
          {blocking > 0 && (
            <div className="pc-unresolved">
              <AlertTriangle size={14} />
              <div>
                <strong>
                  {plan.steps.length ? 'Not included in this plan' : 'Nothing can be applied yet'}
                </strong>
                {plan.unresolved.map((item, index) => (
                  <p key={index}>{item}</p>
                ))}
                <small>Rephrase and plan again, or apply the parts that were understood.</small>
              </div>
            </div>
          )}
          <button className="text-button pc-steps-toggle" onClick={() => setShowSteps(!showSteps)}>
            {showSteps ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {plan.steps.length} engine steps
          </button>
          {showSteps && (
            <ol className="pc-steps">
              {plan.steps.map((step, index) => (
                <li key={index} title={JSON.stringify(step.params, null, 1)}>
                  <code>{step.command}</code>
                  <span>
                    {step.label}
                    {step.expert && <em> · settings chosen by AI</em>}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {stale ? (
            <p className="pc-note">
              <Info size={13} />
              The document changed since this plan. Plan again to apply it to the current version.
            </p>
          ) : (
            plan.steps.length > 0 && (
              <button className="generate-button" disabled={busy} onClick={() => onApply(blocking > 0)}>
                <Sparkles size={16} />
                {blocking > 0
                  ? 'Apply the understood parts'
                  : `Apply ${plan.edits.length || ''} change${plan.edits.length === 1 ? '' : 's'}`}
              </button>
            )
          )}
        </section>
      )}
      {revision && document && document.cursor > 0 && <ResultCheck revision={revision} />}
    </div>
  );
}
