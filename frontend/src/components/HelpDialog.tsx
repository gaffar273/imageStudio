import { useEffect, useRef } from 'react';
import { ArrowUpRight, X } from 'lucide-react';

export function HelpDialog({ close }: { close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="help-dialog"
      aria-label="Getting started"
      onCancel={close}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <section className="help-panel">
        <button autoFocus className="icon-button" aria-label="Close help" onClick={close}>
          <X size={20} />
        </button>
        <span className="eyebrow">A LITTLE INSPIRATION</span>
        <h2>Start with a thought.</h2>
        <p>
          Describe a subject, a setting, and the light. Choose a model and format, then generate your image.
        </p>
        <p>
          Open any image to download it, reuse its settings, or send it to the editor. Paint over an area to
          change just that part.
        </p>
        <p>
          Use <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to generate. Your original files and settings are saved
          automatically in the images folder.
        </p>
        <button className="generate-button" onClick={close}>
          Let's make something
          <ArrowUpRight size={16} />
        </button>
      </section>
    </dialog>
  );
}
