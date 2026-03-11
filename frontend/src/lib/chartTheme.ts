/** Read chart chrome colors from CSS custom properties (theme-aware). */
export function getChartTheme() {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string, fb: string) => s.getPropertyValue(name).trim() || fb;
  return {
    bg:      v("--color-surface",      "#111118"),
    grid:    v("--color-surface-2",    "#1e1e2a"),
    border:  v("--color-border",       "#27272a"),
    text:    v("--color-muted",        "#71717a"),
    textDim: v("--color-border-light", "#52525b"),
    accent:  v("--color-accent",       "#6366f1"),
  };
}
