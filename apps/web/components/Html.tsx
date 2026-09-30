"use client";

import { useMemo } from "react";
import DOMPurify from "dompurify";

const ALLOWED_TAGS = ["p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "h1", "h2", "h3", "blockquote", "hr", "code", "a", "span", "input"];
const ALLOWED_ATTR = ["href", "target", "rel", "data-type", "data-checked", "type", "checked", "disabled"];

export default function Html({ source }: { source: string }) {
  const clean = useMemo(() => {
    if (typeof window === "undefined") return source || "";
    return DOMPurify.sanitize(source || "", { ALLOWED_TAGS, ALLOWED_ATTR });
  }, [source]);
  return <div className="doc-body" dangerouslySetInnerHTML={{ __html: clean }} />;
}
