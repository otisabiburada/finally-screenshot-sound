import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  call,
  definePlugin,
  removeEventListener,
} from "@decky/api";
import { useEffect, useState } from "react";
import { FaCamera } from "react-icons/fa";

// Steam's internal client API (not typed, may change between Steam updates).
declare const SteamClient: any;

type SoundKey = string; // built-in key, or "file:<filename>" for your own files

interface Settings {
  enabled: boolean;
  sound: SoundKey;
  volume: number; // 0-300 (%)
  game_mode_only: boolean;
}

interface Status {
  hook_active: boolean;
  detected: number;
  played: number;
  last_file: string;
  last_time: number;
  last_skip_reason: string;
  player: string;
  watching: number;
}

const BUILTIN_OPTIONS: { data: SoundKey; label: string }[] = [
  { data: "shutter", label: "Camera shutter" },
  { data: "soft_click", label: "Soft click" },
  { data: "chime", label: "Chime" },
  { data: "retro", label: "Retro blip" },
];

interface SoundList {
  custom: { data: string; label: string }[];
  folder: string;
}

const EVENT = "finally_screenshot";

// Survives the quick-access menu being closed/reopened (Content remounts).
let cachedSettings: Settings | null = null;
// Serialises saves so a slow older response can never overwrite a newer choice.
let saveChain: Promise<unknown> = Promise.resolve();

function Content() {
  const [settings, setSettings] = useState<Settings | null>(cachedSettings);
  const [status, setStatus] = useState<Status | null>(null);
  const [sounds, setSounds] = useState<SoundList>({ custom: [], folder: "" });
  const refreshSounds = () =>
    call<[], SoundList>("list_sounds").then(setSounds).catch(() => {});

  useEffect(() => {
    call<[], Settings>("get_settings").then((s: Settings) => {
      cachedSettings = s;
      setSettings(s);
    });
    refreshSounds();
    call<[], Status>("get_status").then(setStatus);
    const listener = addEventListener<[Status]>(EVENT, (s: Status) => setStatus(s));
    return () => {
      removeEventListener(EVENT, listener);
    };
  }, []);

  const update = (patch: Partial<Settings>) => {
    // Optimistic, using the latest known value (not a stale render closure).
    cachedSettings = { ...(cachedSettings ?? settings!), ...patch };
    setSettings(cachedSettings);
    saveChain = saveChain
      .then(() => call<[Partial<Settings>], Settings>("set_settings", patch))
      .then((saved) => {
        // Only adopt the backend's copy once all queued saves are done.
        cachedSettings = saved as Settings;
        setSettings(cachedSettings);
      })
      .catch((e) => console.warn("[Finally Screenshot Sound] save failed:", e));
  };

  if (!settings) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading settings…" />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const options = [
    ...BUILTIN_OPTIONS,
    ...sounds.custom,
  ];
  // Keep a saved-but-missing file visible instead of silently showing the wrong entry.
  if (!options.some((o) => o.data === settings.sound)) {
    options.push({ data: settings.sound, label: settings.sound.replace(/^file:/, "") + " (missing)" });
  }

  const lastSeen =
    status && status.last_time
      ? new Date(status.last_time * 1000).toLocaleTimeString()
      : "None yet";

  return (
    <>
      <PanelSection title="Sound">
        <PanelSectionRow>
          <ToggleField
            label="Play sound on screenshot"
            checked={settings.enabled}
            onChange={(v: boolean) => update({ enabled: v })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Sound"
            rgOptions={options}
            selectedOption={settings.sound}
            onChange={(opt: { data: SoundKey }) => update({ sound: opt.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              `Put .wav, .ogg, .flac or .mp3 files in ${sounds.folder || "~/.config/finally_screenshot_sound/sounds"} ` +
              `or ~/Music or ~/Downloads (${sounds.custom.length} found), then refresh.`
            }
            onClick={refreshSounds}
          >
            Refresh sound list
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Volume"
            description="Above 100% boosts the sound beyond its normal level."
            value={settings.volume}
            min={0}
            max={300}
            step={10}
            showValue
            onChange={(v: number) => update({ volume: v })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => call("test_sound")}>
            Play test sound
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Game Mode only"
            description="Stay silent for screenshots taken in Desktop Mode."
            checked={settings.game_mode_only}
            onChange={(v: boolean) => update({ game_mode_only: v })}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Status">
        <PanelSectionRow>
          <Field
            label="Detection"
            description={
              status?.hook_active
                ? "Instant (Steam hook) with folder watch as backup"
                : "Folder watch only (Steam hook unavailable)"
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
            label="Screenshots this session"
            description={
              status
                ? `${status.detected} detected, last at ${lastSeen}` +
                  (status.last_skip_reason ? ` (silent: ${status.last_skip_reason})` : "")
                : "—"
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
            label="Audio player"
            description={status?.player || "None found — sounds can't play"}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  // Steam's own screenshot notification makes detection near-instant. It never
  // plays a sound by itself: it only tells the backend to scan right away, and
  // the backend plays only when a genuinely new image file exists.
  let unregister: (() => void) | null = null;
  let hooked = false;
  try {
    const sessions = SteamClient?.GameSessions;
    if (sessions && typeof sessions.RegisterForScreenshotNotification === "function") {
      const reg = sessions.RegisterForScreenshotNotification(() => {
        call("scan_now").catch(() => {});
      });
      if (reg && typeof reg.unregister === "function") {
        unregister = () => reg.unregister();
      }
      hooked = true;
    }
  } catch (e) {
    console.warn("[Finally Screenshot Sound] Steam screenshot hook unavailable:", e);
  }
  call("frontend_hook_status", hooked).catch(() => {});

  return {
    name: "Finally Screenshot Sound",
    titleView: <div className={staticClasses.Title}>Finally Screenshot Sound</div>,
    content: <Content />,
    icon: <FaCamera />,
    onDismount() {
      try {
        unregister?.();
      } catch {
        /* ignore */
      }
    },
  };
});
