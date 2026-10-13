# Changelog

## 1.0.1

- **Renamed** from *SANSO Screenshot Sound* to **Finally Screenshot Sound**. Your settings and custom sounds are moved to `~/.config/finally_screenshot_sound/` automatically. Remove the old plugin from Decky after installing this one.
- First GitHub release: release zip with a prebuilt `dist/`, GitHub Actions release workflow, README.
- Fixed the build: an unused import (`TextField`) stopped `tsc` from passing.
- The release zip no longer contains `__pycache__`; `dist/index.js` has no local build paths.

## 1.0.0

- Last version before the GitHub release (as *SANSO Screenshot Sound*).
