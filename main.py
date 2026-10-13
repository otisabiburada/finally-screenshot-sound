"""Finally Screenshot Sound - Decky Loader backend.

Plays a sound whenever Steam saves a screenshot.

Detection model (single source of truth = the filesystem):
  * Steam stores every screenshot as
        <steam>/userdata/<steamid3>/760/remote/<appid>/screenshots/<name>.jpg
    This backend watches those folders by cheap directory-mtime polling and
    plays a sound once per NEW image file. Only a real new file ever makes a
    sound, so there are no double-plays and no false positives from
    deletes/uploads.
  * The frontend additionally hooks Steam's own screenshot notification
    (SteamClient.GameSessions.RegisterForScreenshotNotification). That hook
    never plays a sound itself; it just calls scan_now(), which switches the
    watcher into a fast 50 ms scan burst so the sound lands as soon as the
    file appears. If the hook is unavailable (Steam changes its internal JS
    API), the plain 250 ms polling still works on its own.
"""
import array
import asyncio
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import wave

import decky

PLUGIN_DIR = getattr(decky, "DECKY_PLUGIN_DIR", os.path.dirname(os.path.abspath(__file__)))
SETTINGS_DIR = getattr(decky, "DECKY_SETTINGS_DIR", PLUGIN_DIR)
USER_HOME = getattr(decky, "DECKY_USER_HOME", "") or "/home/deck"
# This plugin used to be called "SANSO Screenshot Sound": move its backup settings and custom sounds over once.
_OLD_CFG = os.path.join(USER_HOME, ".config", "sanso_screenshot_sound")
_NEW_CFG = os.path.join(USER_HOME, ".config", "finally_screenshot_sound")
try:
    if os.path.isdir(_OLD_CFG) and not os.path.exists(_NEW_CFG):
        os.rename(_OLD_CFG, _NEW_CFG)
except OSError:
    pass
SOUNDS_DIR = os.path.join(PLUGIN_DIR, "assets", "sounds")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
# Second copy outside Decky's dirs: survives plugin reinstalls/updates and
# Decky-side settings resets, so the chosen sound always stays chosen.
BACKUP_SETTINGS_FILE = os.path.join(USER_HOME, ".config", "finally_screenshot_sound", "settings.json")
SETTINGS_FILES = (SETTINGS_FILE, BACKUP_SETTINGS_FILE)

BUILTIN_SOUNDS = {
    "shutter": "shutter.wav",
    "soft_click": "soft_click.wav",
    "chime": "chime.wav",
    "retro": "retro.wav",
}
SOUND_KEYS = set(BUILTIN_SOUNDS)
# Drop your own sound files here; they show up in the plugin's Sound list.
CUSTOM_DIR = os.path.join(USER_HOME, ".config", "finally_screenshot_sound", "sounds")
AUDIO_EXTS = (".wav", ".ogg", ".flac", ".mp3")
FILE_PREFIX = "file:"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")

DEFAULTS = {
    "enabled": True,
    "sound": "shutter",
    "volume": 100,          # 0-300 (%; above 100 = boost)
    "game_mode_only": True,
}

POLL_INTERVAL = 0.25        # normal scan cadence (s)
BURST_INTERVAL = 0.05       # scan cadence right after Steam's hook fires (s)
BURST_DURATION = 2.0        # how long a burst lasts (s)
REDISCOVER_EVERY = 15.0     # re-check userdata/ for newly logged-in accounts (s)
MAX_SOUNDS_PER_SCAN = 3     # cap if many files appear at once
MULTI_SOUND_GAP = 0.12      # spacing between sounds in the same scan (s)
GAMEMODE_CACHE_S = 5.0

PLAYERS = ("pw-play", "paplay", "aplay")
MAX_VOLUME = 300            # slider range in %
BOOST_DIR = os.path.join(tempfile.gettempdir(), "finally_screenshot_sound_boost")

log = decky.logger


# ---------------------------------------------------------------------------
# Screenshot folder watcher (pure filesystem logic, no asyncio - easy to test)
# ---------------------------------------------------------------------------
def steam_roots(home=USER_HOME):
    seen, out = set(), []
    for p in (
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
    ):
        try:
            rp = os.path.realpath(p)
        except OSError:
            continue
        if rp not in seen and os.path.isdir(rp):
            seen.add(rp)
            out.append(rp)
    return out


class ScreenshotWatcher:
    def __init__(self, roots):
        self.roots = list(roots)
        self.remote_dirs = []   # userdata/<id>/760/remote paths (may not exist yet)
        self.app_dirs = {}      # remote dir -> [<appid>/screenshots paths]
        self.mtimes = {}        # dir path -> st_mtime_ns at last listing
        self.known = {}         # screenshots dir -> set(filenames)

    # -- discovery -----------------------------------------------------------
    def _list_user_remotes(self):
        found = []
        for root in self.roots:
            ud = os.path.join(root, "userdata")
            try:
                it = os.scandir(ud)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.name.isdigit() and e.name != "0" and e.is_dir():
                            found.append(os.path.join(e.path, "760", "remote"))
                    except OSError:
                        continue
        return sorted(set(found))

    def baseline(self):
        """Record everything that already exists, silently."""
        self.remote_dirs = self._list_user_remotes()
        for r in self.remote_dirs:
            self._scan_remote(r, silent=True)

    def rediscover(self):
        """Pick up accounts that appeared after startup. Their pre-existing
        screenshots are baselined silently (they aren't new captures)."""
        for r in self._list_user_remotes():
            if r not in self.remote_dirs:
                self.remote_dirs.append(r)
                self._scan_remote(r, silent=True)

    # -- scanning ------------------------------------------------------------
    def scan(self):
        new = []
        for r in self.remote_dirs:
            new.extend(self._scan_remote(r, silent=False))
        return new

    def _scan_remote(self, remote, silent):
        try:
            st = os.stat(remote)
        except OSError:
            return []
        if self.mtimes.get(remote) != st.st_mtime_ns or remote not in self.app_dirs:
            self.mtimes[remote] = st.st_mtime_ns
            apps = []
            try:
                with os.scandir(remote) as it:
                    for e in it:
                        try:
                            if e.is_dir():
                                apps.append(os.path.join(e.path, "screenshots"))
                        except OSError:
                            continue
            except OSError:
                return []
            self.app_dirs[remote] = sorted(apps)
        new = []
        for sdir in self.app_dirs.get(remote, ()):
            new.extend(self._scan_shot_dir(sdir, silent))
        return new

    def _scan_shot_dir(self, sdir, silent):
        try:
            st = os.stat(sdir)  # stat BEFORE listing so a racing write re-triggers next tick
        except OSError:
            return []
        if sdir in self.known and self.mtimes.get(sdir) == st.st_mtime_ns:
            return []
        names = set()
        try:
            with os.scandir(sdir) as it:
                for e in it:
                    n = e.name
                    if n.startswith(".") or not n.lower().endswith(IMAGE_EXTS):
                        continue
                    try:
                        if e.is_file():
                            names.add(n)
                    except OSError:
                        continue
        except OSError:
            return []
        self.mtimes[sdir] = st.st_mtime_ns
        prev = self.known.get(sdir)
        self.known[sdir] = names
        if prev is None:
            # First time we see this folder. During baseline it's history;
            # afterwards it means a game's very first screenshot just landed.
            return [] if silent else [os.path.join(sdir, n) for n in sorted(names)]
        return [os.path.join(sdir, n) for n in sorted(names - prev)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def audio_env():
    env = dict(os.environ)
    # Decky's backend is a PyInstaller bundle; its LD_LIBRARY_PATH can break
    # system binaries like pw-play. Restore the original if PyInstaller saved it.
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    uid = os.getuid() or 1000
    if not env.get("XDG_RUNTIME_DIR"):
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    pulse = os.path.join(env["XDG_RUNTIME_DIR"], "pulse", "native")
    if not env.get("PULSE_SERVER") and os.path.exists(pulse):
        env["PULSE_SERVER"] = "unix:" + pulse
    return env


def boosted_wav(path, gain):
    """Return a louder copy of a 16-bit WAV (soft-clipped so it never harshly
    clips), or None if the file isn't a plain 16-bit PCM WAV. Cached in /tmp."""
    if gain <= 1.0 or not path.lower().endswith(".wav"):
        return None
    try:
        st = os.stat(path)
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|{gain:.3f}".encode()).hexdigest()[:16]
        out = os.path.join(BOOST_DIR, key + ".wav")
        if os.path.isfile(out):
            return out
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return None
            params = w.getparams()
            data = array.array("h")
            data.frombytes(w.readframes(w.getnframes()))
        if os.sys.byteorder == "big":
            data.byteswap()
        # Linear up to 0.5 FS, smooth tanh knee above it: keeps the extra gain
        # loud without hard-clipping crackle.
        knee, top = 0.5, 0.98
        res = array.array("h")
        for v in data:
            x = v / 32768.0 * gain
            a = abs(x)
            if a > knee:
                a = knee + (top - knee) * math.tanh((a - knee) / (top - knee))
            res.append(int(math.copysign(a, x) * 32767))
        if os.sys.byteorder == "big":
            res.byteswap()
        os.makedirs(BOOST_DIR, exist_ok=True)
        tmp = out + ".tmp"
        with wave.open(tmp, "wb") as w:
            w.setparams(params)
            w.writeframes(res.tobytes())
        os.replace(tmp, out)
        return out
    except Exception as e:
        log.warning(f"boost failed for {path}: {e}")
        return None


def player_cmd(player, path, volume_pct):
    pct = max(0.0, min(float(MAX_VOLUME), float(volume_pct)))
    gain = pct / 100.0
    if gain > 1.0:
        # Prefer a pre-amplified WAV (works with every player); otherwise fall
        # back to the player's own >100% volume where supported.
        b = boosted_wav(path, gain)
        if b:
            path, gain = b, 1.0
    if player == "pw-play":
        return ["pw-play", f"--volume={gain:.3f}", path]
    if player == "paplay":
        return ["paplay", f"--volume={int(round(gain * 65536))}", path]
    return ["aplay", "-q", path]  # no volume control; last-resort fallback


def gamescope_running():
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return True  # can't tell -> don't block sounds
    for pid in pids:
        try:
            with open(f"/proc/{pid}/comm", "r") as f:
                if f.read().strip().startswith("gamescope"):
                    return True
        except OSError:
            continue
    return False


# Folders scanned for your own sounds (top level only). The first one is created
# automatically; Music and Downloads are included so a file you already have
# there shows up without copying.
SCAN_DIRS = (
    CUSTOM_DIR,
    os.path.join(USER_HOME, "Music"),
    os.path.join(USER_HOME, "Downloads"),
)


def list_custom_sounds():
    """[(key, label)] - key is "file:<path relative to home>"."""
    out = []
    for d in SCAN_DIRS:
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            continue
        for n in names:
            if n.startswith(".") or not n.lower().endswith(AUDIO_EXTS):
                continue
            full = os.path.join(d, n)
            if not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, USER_HOME)
            label = n if d == CUSTOM_DIR else os.path.join(os.path.basename(d), n)
            out.append((FILE_PREFIX + rel, label))
    return out


def resolve_custom(key):
    """Map a "file:..." key to an existing file inside the user's home, or None."""
    rel = key[len(FILE_PREFIX):]
    if rel and "\\" not in rel and not rel.startswith("/"):
        # A bare name (older versions) means the plugin's own sounds folder.
        cands = [os.path.join(CUSTOM_DIR, rel)] if "/" not in rel else []
        cands.append(os.path.join(USER_HOME, rel))
        for c in cands:
            c = os.path.normpath(c)
            if (c == USER_HOME or c.startswith(USER_HOME.rstrip("/") + "/")) and os.path.isfile(c):
                return c
    return None


def valid_sound_key(k):
    if not isinstance(k, str):
        return False
    if k in SOUND_KEYS:
        return True
    # Custom file entries are "file:<path relative to home>"; no escaping home.
    rel = k[len(FILE_PREFIX):]
    return (k.startswith(FILE_PREFIX) and bool(rel) and not rel.startswith("/")
            and "\\" not in rel and ".." not in rel.split("/"))


def sanitize(patch, base):
    out = dict(base)
    if not isinstance(patch, dict):
        return out
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "game_mode_only" in patch:
        out["game_mode_only"] = bool(patch["game_mode_only"])
    if valid_sound_key(patch.get("sound")):
        out["sound"] = patch["sound"]
    if "volume" in patch:
        try:
            out["volume"] = int(max(0, min(MAX_VOLUME, round(float(patch["volume"])))))
        except (TypeError, ValueError):
            pass
    return out


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
class Plugin:
    async def _main(self):
        self.settings = self._load_settings()
        self.players = [p for p in PLAYERS if shutil.which(p)]
        self._burst_until = 0.0
        self._wake = asyncio.Event()
        self._last_discover = time.monotonic()
        self._gm_cache = (0.0, True)
        self._reapers = set()
        self.status = {
            "hook_active": False,
            "detected": 0,
            "played": 0,
            "last_file": "",
            "last_time": 0.0,
            "last_skip_reason": "",
            "player": self.players[0] if self.players else "",
            "watching": 0,
        }
        roots = steam_roots()
        self.watcher = ScreenshotWatcher(roots)
        try:
            await asyncio.to_thread(self.watcher.baseline)
        except Exception as e:
            log.error(f"baseline scan failed: {e}")
        self.status["watching"] = len(self.watcher.known)
        log.info(f"Steam roots={roots} accounts={len(self.watcher.remote_dirs)} "
                 f"screenshot folders={len(self.watcher.known)} players={self.players}")
        self._task = asyncio.create_task(self._watch_loop())

    async def _unload(self):
        t = getattr(self, "_task", None)
        if t:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    # -- settings ------------------------------------------------------------
    def _load_settings(self):
        """Newest readable settings file wins (primary or backup copy)."""
        best, best_m = None, -1.0
        for path in SETTINGS_FILES:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                m = os.path.getmtime(path)
            except FileNotFoundError:
                continue
            except Exception as e:
                log.warning(f"settings {path} unreadable: {e}")
                continue
            if m > best_m:
                best, best_m = data, m
        if best is None:
            return dict(DEFAULTS)
        if isinstance(best, dict) and best.get("sound") == "custom":
            best["sound"] = "shutter"   # v1 typed-path option no longer exists
        return sanitize(best, DEFAULTS)

    def _save_settings(self):
        ok = False
        for path in SETTINGS_FILES:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(self.settings, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
                ok = True
            except Exception as e:
                log.error(f"saving settings to {path} failed: {e}")
        return ok

    # -- frontend-callable ---------------------------------------------------
    async def get_settings(self):
        return self.settings

    async def set_settings(self, patch):
        self.settings = sanitize(patch, self.settings)
        self._save_settings()
        return self.settings

    async def list_sounds(self):
        try:
            os.makedirs(CUSTOM_DIR, exist_ok=True)
        except OSError:
            pass
        found = list_custom_sounds()
        log.info(f"custom sounds: home={USER_HOME} found={len(found)}")
        return {"custom": [{"data": k, "label": l} for k, l in found], "folder": CUSTOM_DIR}

    async def get_status(self):
        return self.status

    async def frontend_hook_status(self, active):
        self.status["hook_active"] = bool(active)
        log.info(f"Steam screenshot hook active: {bool(active)}")
        return True

    async def scan_now(self):
        """Called from Steam's screenshot notification: scan fast for a bit."""
        self._burst_until = time.monotonic() + BURST_DURATION
        self._wake.set()
        return True

    async def test_sound(self):
        return await self._play()

    # -- core loop -----------------------------------------------------------
    async def _watch_loop(self):
        while True:
            self._wake.clear()
            try:
                now = time.monotonic()
                if now - self._last_discover >= REDISCOVER_EVERY:
                    self._last_discover = now
                    await asyncio.to_thread(self.watcher.rediscover)
                new = await asyncio.to_thread(self.watcher.scan)
                self.status["watching"] = len(self.watcher.known)
                if new:
                    await self._on_new_screenshots(new)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"watch loop error: {e}")
            interval = BURST_INTERVAL if time.monotonic() < self._burst_until else POLL_INTERVAL
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def _in_game_mode(self):
        t, val = self._gm_cache
        now = time.monotonic()
        if now - t > GAMEMODE_CACHE_S:
            val = gamescope_running()
            self._gm_cache = (now, val)
        return val

    async def _on_new_screenshots(self, paths):
        self.status["detected"] += len(paths)
        self.status["last_file"] = os.path.basename(paths[-1])
        self.status["last_time"] = time.time()
        log.info(f"new screenshot(s): {[os.path.basename(p) for p in paths]}")
        reason = ""
        if not self.settings["enabled"]:
            reason = "sound turned off"
        elif self.settings["game_mode_only"] and not self._in_game_mode():
            reason = "not in Game Mode"
        self.status["last_skip_reason"] = reason
        if not reason:
            for i in range(min(len(paths), MAX_SOUNDS_PER_SCAN)):
                if i:
                    await asyncio.sleep(MULTI_SOUND_GAP)
                await self._play()
        try:
            await decky.emit("finally_screenshot", self.status)
        except Exception:
            pass

    # -- playback ------------------------------------------------------------
    def _resolve_sound(self):
        key = self.settings["sound"]
        if key.startswith(FILE_PREFIX):
            p = resolve_custom(key)
            if p:
                return p
            log.warning(f"custom sound not found ({key!r}); using shutter")
            key = "shutter"
        return os.path.join(SOUNDS_DIR, BUILTIN_SOUNDS.get(key, "shutter.wav"))

    async def _play(self):
        if not self.players:
            self.players = [p for p in PLAYERS if shutil.which(p)]
            if not self.players:
                log.error("no audio player found (pw-play/paplay/aplay)")
                return False
        player = self.players[0]
        cmd = await asyncio.to_thread(
            player_cmd, player, self._resolve_sound(), self.settings["volume"])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=audio_env(),
            )
        except Exception as e:
            log.error(f"{player} failed to start: {e}")
            self._demote(player)
            return False
        self.status["played"] += 1
        # Don't block on playback; reap in the background (lets sounds overlap).
        t = asyncio.create_task(self._reap(proc, player))
        self._reapers.add(t)
        t.add_done_callback(self._reapers.discard)
        return True

    async def _reap(self, proc, player):
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return
        if proc.returncode != 0:
            log.warning(f"{player} exited {proc.returncode}: {err.decode(errors='replace').strip()[:300]}")
            self._demote(player)

    def _demote(self, player):
        # Move a failing player to the back so the next sound tries another one.
        if player in self.players and len(self.players) > 1:
            self.players.remove(player)
            self.players.append(player)
            self.status["player"] = self.players[0]
            log.info(f"audio player order now {self.players}")
