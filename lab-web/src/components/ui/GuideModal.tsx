import { useEffect, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { HelpCircle, X } from "lucide-react";
import { KeyHint } from "./KeyHint";

/** One paragraph (or custom element) in a guide. */
export type GuideBody = ReactNode;

export interface GuideSection {
  heading?: string;
  body: GuideBody;
}

export interface GuideContent {
  /** Short summary shown at the top. */
  summary?: ReactNode;
  sections?: GuideSection[];
  /** Optional list of `{ keys, label }` pairs rendered as a "Shortcuts" footer. */
  shortcuts?: { keys: string[]; label: string }[];
}

/** Tiny circular `?` button that opens a guide modal.
 *
 *  The modal itself is rendered inline (no portal). Escape closes it; clicking
 *  the backdrop closes it. The trigger is keyboard-focusable and announces the
 *  subject via ``aria-label`` so screen readers have context.
 */
export function GuideButton({
  title,
  guide,
  size = "sm",
  className,
}: {
  title: string;
  guide: GuideContent;
  size?: "sm" | "md";
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        aria-label={`Open guide: ${title}`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
        className={clsx(
          "inline-flex shrink-0 items-center justify-center rounded-full",
          "text-zinc-500 transition-colors hover:text-accent",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          size === "sm" && "size-4",
          size === "md" && "size-5",
          className,
        )}
      >
        <HelpCircle className={clsx(size === "sm" ? "size-3.5" : "size-4")} />
      </button>
      {open && (
        <GuideModal title={title} guide={guide} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

function GuideModal({
  title,
  guide,
  onClose,
}: {
  title: string;
  guide: GuideContent;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={clsx(
          "w-[min(32rem,calc(100vw-2rem))] max-h-[calc(100vh-4rem)]",
          "flex flex-col rounded-xl border border-zinc-800 bg-zinc-950",
          "shadow-2xl ring-1 ring-black/40",
        )}
      >
        <header className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close guide"
            className="inline-flex size-6 items-center justify-center rounded-md text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm text-zinc-300">
          {guide.summary && (
            <p className="text-sm leading-relaxed text-zinc-200">
              {guide.summary}
            </p>
          )}
          {guide.sections?.map((s, i) => (
            <section key={i}>
              {s.heading && (
                <h3 className="mb-1 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                  {s.heading}
                </h3>
              )}
              <div className="text-sm leading-relaxed text-zinc-300">
                {s.body}
              </div>
            </section>
          ))}
          {guide.shortcuts && guide.shortcuts.length > 0 && (
            <section>
              <h3 className="mb-1 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                Shortcuts
              </h3>
              <ul className="space-y-1">
                {guide.shortcuts.map((s) => (
                  <li
                    key={s.label}
                    className="flex items-center justify-between text-sm text-zinc-300"
                  >
                    <span>{s.label}</span>
                    <span className="flex gap-1">
                      {s.keys.map((k) => (
                        <KeyHint key={k}>{k}</KeyHint>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
        <footer className="flex justify-end border-t border-zinc-800 px-4 py-2.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-700"
          >
            Got it
          </button>
        </footer>
      </div>
    </div>
  );
}
