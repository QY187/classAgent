"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";

export default function FeishuEditor({ value, onChange }: { value: string; onChange: (html: string) => void }) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      TaskList,
      TaskItem.configure({ nested: true }),
    ],
    content: value || "",
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
    editorProps: { attributes: { class: "doc-prose" } },
  });

  if (!editor) return <div className="doc-prose doc-prose-loading" />;
  const btn = (active: boolean) => (active ? "doc-toolbar-btn active" : "doc-toolbar-btn");
  return (
    <div className="doc-editor">
      <div className="doc-editor-toolbar">
        <button type="button" className={btn(editor.isActive("bold"))} onClick={() => editor.chain().focus().toggleBold().run()} aria-label="加粗"><b>B</b></button>
        <button type="button" className={btn(editor.isActive("italic"))} onClick={() => editor.chain().focus().toggleItalic().run()} aria-label="斜体"><i>I</i></button>
        <span className="doc-toolbar-sep" />
        <button type="button" className={btn(editor.isActive("heading", { level: 1 }))} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}>H1</button>
        <button type="button" className={btn(editor.isActive("heading", { level: 2 }))} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
        <button type="button" className={btn(editor.isActive("heading", { level: 3 }))} onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>H3</button>
        <span className="doc-toolbar-sep" />
        <button type="button" className={btn(editor.isActive("bulletList"))} onClick={() => editor.chain().focus().toggleBulletList().run()} aria-label="项目符号列表">• 列表</button>
        <button type="button" className={btn(editor.isActive("orderedList"))} onClick={() => editor.chain().focus().toggleOrderedList().run()} aria-label="编号列表">1. 列表</button>
        <button type="button" className={btn(editor.isActive("taskList"))} onClick={() => editor.chain().focus().toggleTaskList().run()} aria-label="待办清单">☑ 待办</button>
        <span className="doc-toolbar-sep" />
        <button type="button" className={btn(editor.isActive("blockquote"))} onClick={() => editor.chain().focus().toggleBlockquote().run()} aria-label="引用">❝ 引用</button>
        <button type="button" className={btn(false)} onClick={() => editor.chain().focus().setHorizontalRule().run()} aria-label="分割线">― 分割线</button>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
