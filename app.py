"""发布入口：把 server/ 加进 sys.path 再起 FastAPI。

平台发布只认目录根的单端口 HTTP 服务，而真正应用在 server/ 下，
所以这里做一层薄壳：不改 server/ 里任何代码，只在启动时补 sys.path。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "server"))

import uvicorn  # noqa: E402
from main import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
