# -*- coding: utf-8 -*-
"""测试用假上游：模拟 DeepSeek 风格，先流式吐英文 reasoning_content，再吐正文 content。"""
import json, time
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

REASON = (
    "Let me think about this step by step. First, I need to understand the user's question. "
    "The user wants to know how to reverse a linked list in Python.\n"
    "There are two common approaches: iterative and recursive. "
    "The iterative approach uses three pointers: prev, curr, and next. "
    "The time complexity is O(n) and the space complexity is O(1).\n"
    "```python\ndef reverse(head):\n    prev = None\n    while head:\n        head.next, prev, head = prev, head, head.next\n    return prev\n```\n"
    "The recursive approach is cleaner but uses O(n) stack space. "
    "I should present both and explain the trade-off."
)
CONTENT = "下面给出反转链表的两种写法，并说明区别。"

@app.post("/{full_path:path}")
async def cc(request: Request, full_path: str = ""):
    body = await request.json()
    stream = body.get("stream", True)
    if not stream:
        return {"id": "mock", "object": "chat.completion", "model": body.get("model", "mock"),
                "choices": [{"index": 0, "message": {"role": "assistant", "reasoning_content": REASON,
                            "content": CONTENT}, "finish_reason": "stop"}]}

    def gen():
        # 逐小块吐 reasoning（模拟真实 token 流），每 6 字一块
        for i in range(0, len(REASON), 6):
            obj = {"id": "mock", "object": "chat.completion.chunk", "model": body.get("model", "mock"),
                   "choices": [{"index": 0, "delta": {"reasoning_content": REASON[i:i + 6]}, "finish_reason": None}]}
            yield ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
            time.sleep(0.005)
        obj = {"id": "mock", "object": "chat.completion.chunk", "model": body.get("model", "mock"),
               "choices": [{"index": 0, "delta": {"content": CONTENT}, "finish_reason": None}]}
        yield ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
        yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9911, log_level="warning")
