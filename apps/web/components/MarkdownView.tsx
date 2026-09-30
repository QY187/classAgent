"use client";

import { type ReactNode } from "react";

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${keyPrefix}-${index}`}>{part}</span>;
  });
}

function renderMarkdown(source: string): ReactNode[] {
  const lines = source.split("\n");
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let key = 0;

  const flushList = () => {
    if (!list) return;
    const items = list.items;
    const ordered = list.ordered;
    const node = ordered
      ? <ol key={`list-${key++}`}>{items.map((item, index) => <li key={index}>{renderInline(item, `ol-${key}-${index}`)}</li>)}</ol>
      : <ul key={`list-${key++}`}>{items.map((item, index) => <li key={index}>{renderInline(item, `ul-${key}-${index}`)}</li>)}</ul>;
    blocks.push(node);
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = heading[1].length;
      const text = heading[2];
      const node = level === 1 ? <h1 key={`h-${key++}`}>{renderInline(text, `h1-${key}`)}</h1>
        : level === 2 ? <h2 key={`h-${key++}`}>{renderInline(text, `h2-${key}`)}</h2>
        : <h3 key={`h-${key++}`}>{renderInline(text, `h3-${key}`)}</h3>;
      blocks.push(node);
      continue;
    }
    const unordered = /^[-*]\s+(.*)$/.exec(line);
    if (unordered) {
      if (!list || list.ordered) { flushList(); list = { ordered: false, items: [] }; }
      list.items.push(unordered[1]);
      continue;
    }
    const ordered = /^\d+\.\s+(.*)$/.exec(line);
    if (ordered) {
      if (!list || !list.ordered) { flushList(); list = { ordered: true, items: [] }; }
      list.items.push(ordered[1]);
      continue;
    }
    if (line.trim() === "") {
      flushList();
      continue;
    }
    flushList();
    blocks.push(<p key={`p-${key++}`}>{renderInline(line, `p-${key}`)}</p>);
  }
  flushList();
  return blocks;
}

export default function MarkdownView({ source }: { source: string }) {
  return <div className="markdown-body">{renderMarkdown(source)}</div>;
}
