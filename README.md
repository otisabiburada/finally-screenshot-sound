# Finally Screenshot Sound

<p align="center">
  <a href="../../releases/latest"><img src="https://img.shields.io/badge/download-latest%20release-1a9fff?style=for-the-badge" alt="Download"></a>
  <img src="https://img.shields.io/badge/Decky%20Loader-plugin-6f42c1?style=for-the-badge" alt="Decky Loader plugin">
  <img src="https://img.shields.io/badge/Steam%20Deck-Gaming%20Mode-2a475e?style=for-the-badge" alt="Steam Deck">
  <img src="https://img.shields.io/badge/license-BSD--3--Clause-555?style=for-the-badge" alt="License">
</p>

<p align="center">
  <b>Plays a sound whenever Steam saves a screenshot (Steam + R1) on your Steam Deck.</b><br>
  Near-instant, four built-in sounds, your own sounds, adjustable volume. No build step: download the zip and install.
</p>

---

## ✨ Features

| | |
|---|---|
| 📸 **Near-instant** | Hooks Steam's screenshot notification, with a folder watch (250 ms) as backup if that hook ever breaks. |
| 🔊 **Four built-in sounds** | Camera shutter, soft click, chime, retro blip. |
| 🎵 **Your own sounds** | Drop `.wav`, `.ogg`, `.flac` or `.mp3` files into `~/.config/finally_screenshot_sound/sounds/` (or `~/Music`, `~/Downloads`), press *Refresh sound list*, pick them in the dropdown. |
| 🎚️ **Volume up to 300%** | Above 100% boosts quiet sounds. |
| 🎮 **Game Mode only** | Optionally stay silent for screenshots taken in Desktop Mode. |
| 🩺 **Status** | Shows whether the Steam hook is active, how many screenshots were seen, and which audio player is used. |

## 📥 Install

> Requires [Decky Loader](https://decky.xyz) on your Steam Deck.

### Option A: from the release zip (recommended)

1. Go to the [**latest release**](../../releases/latest) and copy the link of `Finally-Screenshot-Sound-vX.Y.Z.zip`.
2. On the Deck, open **Decky settings → General** and turn on **Developer mode**.
3. Open **Decky settings → Developer → Third-Party Plugins → Install Plugin from URL**, paste the link and press **Install**.

You can also download the zip in Desktop Mode and use **Install Plugin from ZIP File** on the same page.

### Option B: by hand (Konsole, Desktop Mode)

```bash
cd ~/Downloads
unzip Finally-Screenshot-Sound-v*.zip
sudo rm -rf ~/homebrew/plugins/Finally_Screenshot_Sound "$HOME/homebrew/plugins/Finally Screenshot Sound"
sudo cp -r Finally_Screenshot_Sound ~/homebrew/plugins/
sudo systemctl restart plugin_loader
```

### Updating (for example from 1.0.0)

Install the new zip the same way, over the old one; Decky replaces it in place.

**Coming from the old name (SANSO Screenshot Sound 1.0.0)?** The plugin was renamed, so Decky sees it as a new plugin: install this one, then remove the old *SANSO Screenshot Sound* from the Decky plugin list (or delete its folder in `~/homebrew/plugins`). Your sound, volume and custom sounds are moved over automatically the first time the new plugin starts.

## 🕹️ Use

Open the **Quick Access menu (•••) → Finally Screenshot Sound**.

- **Play sound on screenshot** turns it on or off.
- **Sound** picks a built-in or your own sound. **Play test sound** previews it.
- **Volume** goes from 0 to 300%.
- **Game Mode only** keeps Desktop Mode screenshots silent.
- **Status** shows *Detection* (Steam hook or folder watch only), the screenshots seen this session, and the audio player.

## 🔧 How it works

- The Python part watches `userdata/<id>/760/remote/<appid>/screenshots/` and plays one sound per new image file (up to 3 at once).
- The panel part hooks Steam's screenshot notification only to trigger an immediate scan; the sound is played only when a genuinely new image exists.
- Settings are saved in Decky's settings folder, with a backup in `~/.config/finally_screenshot_sound/`.
- Audio goes through `pw-play`, then `paplay`, then `aplay`, whichever works.

## 🛠️ Building from source

You don't need this to use the plugin; the release zip is ready to install.

```bash
npm install
npm run typecheck
npm run build      # dist/index.js
npm run package    # release/Finally-Screenshot-Sound-vX.Y.Z.zip
python3 tools/gen_sounds.py   # optional: regenerate the built-in sounds
```

Pushing a tag like `v1.0.1` (or `1.0.1`) runs the GitHub Actions workflow, which builds the zip and attaches it to a GitHub release. The tag must match the version in `package.json`.

```
src/index.tsx     Quick Access panel and the screenshot hook
main.py           Python part: folder watch, sound playback, settings
assets/sounds/    built-in sounds (made by tools/gen_sounds.py)
tools/            build script, sound generator and the Decky globals it uses
```

## 📄 License and credits

BSD-3-Clause © Finally. See [LICENSE](LICENSE) and [CHANGELOG](CHANGELOG.md).

Not affiliated with Valve.
