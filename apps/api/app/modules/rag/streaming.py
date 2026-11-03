"""读取模型流，并只发布完整、可校验来源的结论。"""
import json
import re
import httpx
from ...core.model_budget import REJECTED_STATUSES, model_reservation


class ClaimStream:
    def __init__(self):
        self.raw = ""
        self.position = None
        self.claims = []
        self.decoder = json.JSONDecoder()

    def feed(self, text):
        self.raw += text
        if self.position is None:
            match = re.search(r'"claims"\s*:\s*\[', self.raw)
            if not match:
                return False
            self.position = match.end()
        changed = False
        while len(self.claims) < 8:
            while self.position < len(self.raw) and self.raw[self.position] in " \r\n\t,":
                self.position += 1
            try:
                claim, end = self.decoder.raw_decode(self.raw, self.position)
            except ValueError:
                break
            self.position = end
            self.claims.append(claim)
            changed = True
        return changed


def stream_completion(url, headers, body, on_claims, on_check=None):
    parser = ClaimStream()
    finished = False
    with model_reservation(body, purpose="rag_answer_stream") as reservation:
        request_body = {**body, "stream": True}
        if reservation:
            request_body.update(max_tokens=body.get("max_tokens", 4000), stream_options={"include_usage": True})
            reservation.sent = True
        with httpx.stream("POST", url, headers=headers, json=request_body, timeout=120) as response:
            if reservation and response.status_code in REJECTED_STATUSES:
                reservation.settle(0)
            response.raise_for_status()
            for line in response.iter_lines():
                if on_check is not None:
                    on_check()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    finished = True
                    break
                payload = json.loads(data)
                if payload.get("error"):
                    raise ValueError("模型流返回错误")
                if reservation and payload.get("usage") and not reservation.finished:
                    reservation.usage(payload["usage"])
                choices = payload.get("choices", [])
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content") or ""
                if not isinstance(content, str):
                    raise ValueError("无效的模型片段")
                if parser.feed(content):
                    on_claims(parser.claims)
    if not finished:
        raise ValueError("模型流意外中断")
    return parser.raw
