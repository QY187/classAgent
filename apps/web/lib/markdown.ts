function escapeHtml(value: string): string {
  return value.replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char] as string));
}

function inlineHtml(text: string): string {
  return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

export function markdownToHtml(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushList = () => {
    if (!list) return;
    const tag = list.ordered ? "ol" : "ul";
    out.push(`<${tag}>${list.items.map((item) => `<li>${inlineHtml(item)}</li>`).join("")}</${tag}>`);
    list = null;
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = heading[1].length;
      out.push(`<h${level}>${inlineHtml(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*[-*]\s+(.*)$/.test(line)) {
      const body = line.replace(/^\s*[-*]\s+/, "");
      if (!list || list.ordered) { flushList(); list = { ordered: false, items: [] }; }
      list.items.push(body);
      continue;
    }
    if (/^\s*\d+\.\s+(.*)$/.test(line)) {
      const body = line.replace(/^\s*\d+\.\s+/, "");
      if (!list || !list.ordered) { flushList(); list = { ordered: true, items: [] }; }
      list.items.push(body);
      continue;
    }
    if (/^>\s?(.*)$/.test(line)) {
      flushList();
      out.push(`<blockquote>${inlineHtml(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      flushList();
      out.push("<hr/>");
      continue;
    }
    if (line.trim() === "") { flushList(); continue; }
    flushList();
    out.push(`<p>${inlineHtml(line)}</p>`);
  }
  flushList();
  return out.join("\n");
}
