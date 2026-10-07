export type ChatLesson = { id: string; title: string; course_id: string; course_name: string };
export type Conversation = { id: string; lesson_id: string; title: string; created_at: string; updated_at: string; generating: boolean };
export type ChatCitation = { id: number; lesson_id: string; lesson_title: string; start_ms: number; snippet: string };
export type ChatMessage = { id: string; request_id: string; position: number; role: "user" | "assistant"; content: string; status: "pending" | "completed" | "failed"; citations: ChatCitation[]; error_message: string | null; created_at: string };
export type ChatHistory = { conversation: Conversation; messages: ChatMessage[] };
export type ChatSearchResult = Conversation & { lesson_title: string; course_name: string };
