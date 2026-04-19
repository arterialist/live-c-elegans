import { clsx } from "clsx";

/** Small keyboard key pill.
 *
 *  Used to surface the global shortcut next to the control that triggers it
 *  (tab buttons, transport HUD, App settings reference panel). Keeping one
 *  component means we only tune the look once.
 */
export function KeyHint({
  children,
  size = "xs",
  className,
}: {
  children: React.ReactNode;
  size?: "xxs" | "xs" | "sm";
  className?: string;
}) {
  return (
    <kbd
      className={clsx(
        "rounded border border-zinc-700 bg-zinc-950 font-mono text-zinc-300",
        size === "xxs" && "px-1 py-[1px] text-[9px] leading-[12px]",
        size === "xs" && "px-1.5 py-0.5 text-[10px] leading-none",
        size === "sm" && "px-1.5 py-0.5 text-[11px] leading-none",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
