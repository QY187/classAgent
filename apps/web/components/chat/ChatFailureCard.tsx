export default function ChatFailureCard({ reason, requestId }: { reason: string | null; requestId: string }) {
  return <section className="chat-failure-card" role="alert" aria-label="回答失败原因">
    <strong>本次回答失败</strong>
    <p><span>失败原因：</span>{reason || "暂时无法确认具体原因，请稍后重试或查看执行详情。"}</p>
    <small>请求编号：<code>{requestId}</code></small>
  </section>;
}
