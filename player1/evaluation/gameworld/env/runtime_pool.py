"""Persistent HTTP and browser runtimes for GameWorld controller sessions."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.async_api import Browser, async_playwright

from .browser_manager import BrowserConfig, BrowserGameManager
from .game_launcher import GameLauncher

LOGGER = logging.getLogger(__name__)


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        host = self.headers["Host"].partition(":")[0].lower()
        self.directory = str(self.server.game_roots[host])  # type: ignore[attr-defined]
        return super().translate_path(path)

    def copyfile(self, source: Any, outputfile: Any) -> None:
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _GameStaticServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, _QuietStaticHandler)
        self.game_roots: dict[str, Path] = {}

    def register(self, root: Path) -> str:
        token = hashlib.sha256(str(root).encode()).hexdigest()[:16]
        host = f"gw-{token}.localhost"
        self.game_roots[host] = root
        return host


class PersistentGameServer:
    """Serve game directories as virtual roots for one controller lifetime."""

    def __init__(self) -> None:
        self._server: _GameStaticServer | None = None
        self._thread: threading.Thread | None = None

    def ensure(self, root: Path, *, preferred_port: int | None = None) -> str:
        resolved = root.expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"Game directory not found: {resolved}")
        if self._server is None:
            self._server = _GameStaticServer(
                ("127.0.0.1", int(preferred_port or 0))
            )
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="gameworld-static-server",
                daemon=True,
            )
            self._thread.start()
        host = self._server.register(resolved)
        port = self._server.server_port
        return f"http://{host}:{port}"

    def game_url(
        self,
        game_id: str,
        *,
        preferred_port: int | None = None,
        html_file: str = GameLauncher.DEFAULT_HTML,
    ) -> str:
        game_dir = GameLauncher.resolve_game_directory(game_id)
        if not game_dir.is_dir():
            raise FileNotFoundError(
                f"Game directory not found: {game_dir}. Base dir: {game_dir.parent}"
            )
        origin = self.ensure(game_dir, preferred_port=preferred_port)
        path = "/".join(quote(part) for part in Path(html_file).parts)
        return f"{origin}/{path}"

    def close(self) -> None:
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)


class SharedChromiumRuntime:
    """Own one Chromium process shared by GameWorld browser sessions."""

    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browser: Browser | None = None
        self._launch_key: tuple[bool, tuple[str, ...]] | None = None
        self._lock = asyncio.Lock()

    async def acquire(self, *, headless: bool, args: list[str]) -> tuple[Browser, bool]:
        launch_key = (bool(headless), tuple(args))
        async with self._lock:
            if (
                self._browser is not None
                and self._browser.is_connected()
                and self._launch_key == launch_key
            ):
                return self._browser, True
            await self.close()
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=args,
            )
            self._launch_key = launch_key
            return self._browser, False

    async def close(self) -> None:
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None
        self._launch_key = None
        if browser is not None:
            try:
                await browser.close()
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("GameWorld shared Chromium close skipped: %s", exc)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("GameWorld Playwright stop skipped: %s", exc)


@dataclass(frozen=True)
class GameWorldBrowserKey:
    game_id: str
    game_url: str
    random_seed: int
    width: int
    height: int
    headless: bool
    speed_multiplier: float
    zoom_level: float

    @classmethod
    def from_config(cls, game_id: str, config: BrowserConfig) -> "GameWorldBrowserKey":
        return cls(
            game_id=str(game_id),
            game_url=str(config.game_url),
            random_seed=int(config.random_seed or 0),
            width=int(config.width),
            height=int(config.height),
            headless=bool(config.headless),
            speed_multiplier=float(config.speed_multiplier),
            zoom_level=float(config.zoom_level),
        )


@dataclass
class GameWorldBrowserLease:
    key: GameWorldBrowserKey
    manager: BrowserGameManager
    reused: bool


class GameWorldBrowserPool:
    """Share server and Chromium process while isolating every trial context."""

    def __init__(self) -> None:
        self.server = PersistentGameServer()
        self.browser_runtime = SharedChromiumRuntime()
        self._leased: GameWorldBrowserLease | None = None

    def game_url(self, game_id: str, *, preferred_port: int | None = None) -> str:
        return self.server.game_url(game_id, preferred_port=preferred_port)

    async def acquire(
        self,
        key: GameWorldBrowserKey,
        config: BrowserConfig,
    ) -> GameWorldBrowserLease:
        if self._leased is not None:
            raise RuntimeError("GameWorld browser pool already has an active lease")

        manager = BrowserGameManager(config, browser_runtime=self.browser_runtime)
        try:
            await manager.start()
        except Exception as exc:
            try:
                await manager.close()
            except Exception as close_exc:  # noqa: BLE001
                exc.add_note(f"GameWorld partial browser cleanup also failed: {close_exc}")
            raise

        lease = GameWorldBrowserLease(
            key=key,
            manager=manager,
            reused=bool(manager.shared_browser_reused),
        )
        self._leased = lease
        return lease

    async def release(self, lease: GameWorldBrowserLease, *, reusable: bool) -> None:
        if self._leased is not lease:
            raise RuntimeError("GameWorld browser lease is not active in this pool")
        self._leased = None
        del reusable
        await lease.manager.close()

    async def shutdown(self) -> None:
        lease, self._leased = self._leased, None
        if lease is not None:
            await lease.manager.close()
        await self.browser_runtime.close()
        self.server.close()


__all__ = [
    "GameWorldBrowserKey",
    "GameWorldBrowserLease",
    "GameWorldBrowserPool",
    "PersistentGameServer",
    "SharedChromiumRuntime",
]
