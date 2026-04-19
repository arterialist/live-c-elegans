import type { ReactNode } from "react";

export function Placeholder({ body }: { body: string[] }) {
  return (
    <ul className="space-y-2 text-sm text-zinc-400">
      {body.map((line, i) => (
        <li key={i} className="leading-relaxed">
          {line}
        </li>
      ))}
    </ul>
  );
}

export function TabShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 px-5 pt-5">
        <h2 className="text-sm font-semibold tracking-wide text-zinc-200 uppercase">
          {title}
        </h2>
        {subtitle && <p className="mt-1 text-xs text-zinc-500">{subtitle}</p>}
      </header>
      <div className="min-h-0 flex-1 px-5 py-4">{children}</div>
    </div>
  );
}
