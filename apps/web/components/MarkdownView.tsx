"use client";
import { type ReactNode } from "react";

type Options = { citationIds?: number[]; onCitation?: (id: number) => void };
function safeHref(value: string): string | null {
  if (/[\s\\\u0000-\u001f]/.test(value)) return null;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null; } catch { return null; }
}
function inline(text: string, prefix: string, options: Options): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]\n]+\]\([^\s)]+\)|\[\d+\])/g);
  return parts.map((part, index) => {
    const key = `${prefix}-${index}`;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={key}>{inline(part.slice(2, -2), key, options)}</strong>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) { const href = safeHref(link[2]); if (href) return <a key={key} href={href} rel="noopener noreferrer">{inline(link[1], key, {})}</a>; }
    const citation = /^\[(\d+)\]$/.exec(part);
    if (citation && options.onCitation && options.citationIds?.includes(Number(citation[1]))) return <button key={key} type="button" className="chat-inline-citation" aria-label={`查看引用 ${citation[1]}`} onClick={() => options.onCitation?.(Number(citation[1]))}>{part}</button>;
    return part;
  });
}
function cells(line: string): string[] { return line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, "|")); }
const listItem = /^(\s*)([-*]|\d+[.)])\s+(.*)$/;
function blocks(lines: string[], options: Options, prefix = "md", depth = 0): ReactNode[] {
  if (depth > 12) return [<p key={prefix}>{lines.join("\n")}</p>];
  const result: ReactNode[] = [];
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trimEnd(), key = `${prefix}-${index}`;
    if (!line.trim()) continue;
    const fence = /^\s*(`{3,}|~{3,})([\w+-]*)\s*$/.exec(line);
    if (fence) {
      const code: string[] = []; index++;
      while (index < lines.length && !new RegExp(`^\\s*${fence[1][0]}{${fence[1].length},}\\s*$`).test(lines[index])) code.push(lines[index++]);
      result.push(<pre key={key}><code className={fence[2] ? `language-${fence[2]}` : undefined}>{code.join("\n")}</code></pre>); continue;
    }
    if (/^\s*>/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*> ?/, ""));
      index--; result.push(<blockquote key={key}>{blocks(quote, options, key, depth + 1)}</blockquote>); continue;
    }
    const headers = cells(line), separators = index + 1 < lines.length ? cells(lines[index + 1]) : [];
    if (line.includes("|") && separators.length === headers.length && separators.every(cell => /^:?-{3,}:?$/.test(cell))) {
      const rows: string[][] = []; index++;
      while (index + 1 < lines.length && lines[index + 1].trim() && lines[index + 1].includes("|")) rows.push(cells(lines[++index]));
      const align = separators.map(cell => cell.startsWith(":") && cell.endsWith(":") ? "center" as const : cell.endsWith(":") ? "right" as const : "left" as const);
      result.push(<div className="markdown-table-scroll" role="region" aria-label="表格，可横向滚动" tabIndex={0} key={key}><table><thead><tr>{headers.map((cell, col) => <th key={col} scope="col" style={{ textAlign: align[col] }}>{inline(cell, `${key}-h${col}`, options)}</th>)}</tr></thead><tbody>{rows.map((row, r) => <tr key={r}>{headers.map((_, col) => <td key={col} style={{ textAlign: align[col] }}>{inline(row[col] || "", `${key}-${r}-${col}`, options)}</td>)}</tr>)}</tbody></table></div>); continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) { const content = inline(heading[2], key, options); result.push(heading[1].length === 1 ? <h1 key={key}>{content}</h1> : heading[1].length === 2 ? <h2 key={key}>{content}</h2> : <h3 key={key}>{content}</h3>); continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { result.push(<hr key={key} />); continue; }
    const first = listItem.exec(line);
    if (first) {
      const indent = first[1].length, ordered = /^\d/.test(first[2]), items: ReactNode[] = [];
      while (index < lines.length) {
        const match = listItem.exec(lines[index]);
        if (!match || match[1].length !== indent || /^\d/.test(match[2]) !== ordered) break;
        const nested: string[] = [], itemKey = `${key}-i${index}`;
        const body = match[3]; index++;
        while (index < lines.length && (!lines[index].trim() || (lines[index].match(/^\s*/)?.[0].length || 0) > indent)) {
          nested.push(lines[index].slice(Math.min(indent + 2, lines[index].match(/^\s*/)?.[0].length || 0))); index++;
        }
        items.push(<li key={itemKey}>{inline(body, itemKey, options)}{blocks(nested, options, itemKey, depth + 1)}</li>);
      }
      index--; result.push(ordered ? <ol key={key} start={Number.parseInt(first[2], 10)}>{items}</ol> : <ul key={key}>{items}</ul>); continue;
    }
    result.push(<p key={key}>{inline(line, key, options)}</p>);
  }
  return result;
}
export default function MarkdownView({ source, citationIds, onCitation }: { source: string } & Options) { return <div className="markdown-body">{blocks(source.replace(/\r\n/g, "\n").split("\n"), { citationIds, onCitation })}</div>; }
