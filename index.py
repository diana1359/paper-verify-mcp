"""
api/index.py  —  Vercel 서버리스 진입점

Vercel의 Python 런타임은 이 파일의 `app` (ASGI 콜러블) 을 자동으로 감지해 실행한다.
서버리스 환경에서 FastMCP를 안전하게 돌리기 위해 두 가지를 처리한다.

  1) stateless_http=True  — 요청 간 세션 상태를 유지하지 않음 (인스턴스가 매번 다를 수 있음).
  2) lifespan shim        — 플랫폼이 ASGI lifespan 을 실행하지 않아도,
                            첫 HTTP 요청 때 FastMCP 세션 매니저를 한 번 초기화한다.
                            (초기화 안 하면 "Task group is not initialized" 로 죽음)
"""

import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # 상위 폴더의 server.py 를 import

from server import mcp

# FastMCP 를 Streamable HTTP ASGI 앱으로. Vercel 호스트를 허용목록에 넣어 DNS rebinding 보호를 통과.
_base_app = mcp.http_app(
    path="/mcp",
    stateless_http=True,
    allowed_hosts=["*"],
    allowed_origins=["*"],
    json_response=True,  # 서버리스: SSE 스트림 대신 단일 JSON 응답
)


class _LifespanShim:
    """플랫폼이 lifespan 을 실행하든 안 하든, 세션 매니저가 반드시 한 번 초기화되게 보장."""

    def __init__(self, app):
        self.app = app
        self._cm = None
        self._ready = False
        self._lock = asyncio.Lock()

    async def _ensure_started(self):
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            self._cm = self.app.router.lifespan_context(self.app)
            await self._cm.__aenter__()
            self._ready = True

    async def __call__(self, scope, receive, send):
        # 플랫폼이 직접 lifespan 을 구동하면 그대로 위임하고 초기화 완료로 표시.
        if scope["type"] == "lifespan":
            self._ready = True
            await self.app(scope, receive, send)
            return
        # 일반 HTTP 요청: lifespan 이 안 돌았다면 지금 초기화.
        await self._ensure_started()
        await self.app(scope, receive, send)


app = _LifespanShim(_base_app)
