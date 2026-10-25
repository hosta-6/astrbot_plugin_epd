"""墨水屏推送 · /epd

把群里的文字或图片推到 hosta 那块 768x552 四色墨水屏上。
图片一律走标准调色管线（自动色阶 → 暖色提亮/冷色压黑白 → 锐化 30 → FS 抖动 85%）。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import urllib.request
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

PLUGIN_NAME = "astrbot_plugin_epd"

EPD_DIR = os.environ.get("EPD_WORKDIR", "/root/remote-control/epd")
PUSH = os.path.join(EPD_DIR, "push.sh")
PREVIEW = os.path.join(EPD_DIR, "std_preview.png")
INBOX = os.path.join(EPD_DIR, "inbox")

HELP = (
    "🐾 墨水屏用法喵：\n"
    "/epd 想说的话 …… 推一行大字上屏\n"
    "/epd（带图）    …… 图片按标准调色推上屏\n"
    "/epd 存 想说的话 …… 推上屏并存进板子图库\n"
    "/epd 帮助"
)


def _ensure_inbox() -> str:
    os.makedirs(INBOX, exist_ok=True)
    return INBOX


class EpdPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.conf = config if config is not None else {}
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- 配置
    def c(self, key: str, default: Any = None) -> Any:
        try:
            v = self.conf.get(key, default)
        except Exception:
            v = getattr(self.conf, key, default)
        return default if v is None else v

    # ---------------------------------------------------------------- 工具
    async def _run(self, args: list[str], timeout: int = 200) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", PUSH, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, out.decode("utf-8", "ignore")
        except asyncio.TimeoutError:
            return 1, "⏰ 超时了喵，可能是电脑没开或者没连 MoInk-7800 热点"
        except Exception as e:  # noqa: BLE001
            return 1, f"执行出错：{e}"

    async def _grab_image(self, event: AstrMessageEvent) -> str | None:
        """从消息里取第一张图，返回本地路径"""
        try:
            chain = event.message_obj.message
        except Exception:
            return None
        for comp in chain:
            if isinstance(comp, Image):
                p = getattr(comp, "path", None)
                if p and os.path.isfile(p):
                    return p
                url = getattr(comp, "url", None) or getattr(comp, "file", None)
                if url and str(url).startswith("http"):
                    box = _ensure_inbox()

                    def _dl(u=url):
                        req = urllib.request.Request(
                            u, headers={"User-Agent": "Mozilla/5.0"})
                        data = urllib.request.urlopen(req, timeout=40).read()
                        fd, path = tempfile.mkstemp(suffix=".png", dir=box)
                        os.write(fd, data)
                        os.close(fd)
                        return path

                    try:
                        return await asyncio.to_thread(_dl)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[epd] 图片下载失败: {e}")
                        return None
        return None

    def _cooling(self, event: AstrMessageEvent) -> int:
        cd = int(self.c("cooldown", 15))
        key = f"{event.unified_msg_origin}"
        now = time.time()
        last = self._last.get(key, 0)
        if now - last < cd:
            return int(cd - (now - last))
        self._last[key] = now
        return 0

    # ---------------------------------------------------------------- 命令
    @filter.command("epd")
    async def cmd_epd(self, event: AstrMessageEvent):
        """/epd 文字 或 /epd + 图片"""
        raw = (event.get_message_str() or "").strip()
        for p in ("/epd", "epd"):
            if raw.lower().startswith(p):
                raw = raw[len(p):].strip()
                break

        if raw in ("帮助", "help", "?", "？"):
            yield event.plain_result(HELP)
            return

        img = await self._grab_image(event)

        if not raw and not img:
            yield event.plain_result(HELP)
            return

        wait = self._cooling(event)
        if wait > 0:
            yield event.plain_result(f"慢点儿喵～还有 {wait} 秒才能再推一次🫠")
            return

        save = False
        if raw.startswith("存"):
            save = True
            raw = raw[1:].strip()

        args: list[str] = []
        if save:
            args.append("--save")

        if img:
            args.append(img)
        elif raw:
            args.append("--text")
            args.append(raw[:60])
        else:
            yield event.plain_result("要给咱一句话或者一张图喵～")
            return

        async with self._lock:
            code, out = await self._run(args)

        ok = code == 0 and "上屏成功" in out
        detail = out.strip().splitlines()[-1] if out.strip() else ""

        if ok:
            ms = ""
            if "|" in out:
                parts = [x.strip() for x in out.splitlines() if "|" in x]
                if parts:
                    ms = parts[-1]
            txt = "🖥️ 推上屏啦喵～" + (f"\n{ms}" if ms else "")
            if save:
                txt += "\n（顺手存进板子图库了）"
            yield event.plain_result(txt)
            if img and os.path.isfile(PREVIEW):
                yield event.image_result(PREVIEW)
        else:
            yield event.plain_result(
                f"😿 没推上去……\n{detail}\n"
                "多半是电脑没开机、或者没连 MoInk-7800 那个热点喵"
            )

    @filter.command("epd帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP)

    async def terminate(self):
        pass
