/**
 * Helpers for the agents' markdown: a table of contents, a plain-text excerpt,
 * and reading time.
 */

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_~[\]()]/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60);
}

export interface TocEntry {
  id: string;
  text: string;
  level: 2 | 3;
}

export function tableOfContents(markdown: string): TocEntry[] {
  const entries: TocEntry[] = [];
  const seen = new Map<string, number>();
  for (const line of markdown.split("\n")) {
    const match = /^(#{2,3})\s+(.+?)\s*#*$/.exec(line.trim());
    if (!match) continue;
    const text = stripInline(match[2]);
    const base = slugify(text) || "section";
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    entries.push({ id: count ? `${base}-${count}` : base, text, level: match[1].length as 2 | 3 });
  }
  return entries;
}

function stripInline(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .trim();
}

/** First substantial prose paragraph — skips headings, tables, lists and short lines */
export function excerpt(markdown: string, maxLength = 260): string {
  const paragraphs = markdown.split(/\n\s*\n/);
  for (const block of paragraphs) {
    const trimmed = block.trim();
    if (!trimmed || /^(#|\||[-*+]\s|\d+\.\s|>|```)/.test(trimmed)) continue;
    const text = stripInline(trimmed.replace(/\n/g, " "));
    if (text.length < 80) continue;
    return text.length > maxLength ? `${text.slice(0, maxLength).replace(/\s+\S*$/, "")}…` : text;
  }
  return "";
}

export function readingMinutes(markdown: string): number {
  const words = markdown.split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 220));
}
