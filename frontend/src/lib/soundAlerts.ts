/**
 * Sound alerts for trading events using Web Audio API.
 *
 * No external audio files needed — generates tones programmatically.
 * Respects user preference via localStorage 'elder_sound_alerts' key.
 */

type AlertType =
  | "signal"         // New actionable signal (ascending chime)
  | "trade"          // Trade executed (short confirmation beep)
  | "stop_hit"       // Stop loss hit (descending warning)
  | "target_hit"     // Target hit (happy ascending)
  | "order_rejected" // Order rejected (error buzz)
  | "eod_close"      // EOD position closed (neutral bell)
  | "error";         // System error (low buzz)

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) {
    try {
      audioCtx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    } catch {
      return null;
    }
  }
  return audioCtx;
}

function isEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("elder_sound_alerts") !== "false";
}

export function setSoundEnabled(enabled: boolean): void {
  localStorage.setItem("elder_sound_alerts", enabled ? "true" : "false");
}

export function isSoundEnabled(): boolean {
  return isEnabled();
}

function playTone(
  frequency: number,
  duration: number,
  type: OscillatorType = "sine",
  volume: number = 0.3,
): void {
  const ctx = getAudioContext();
  if (!ctx || !isEnabled()) return;

  // Resume context if suspended (browser autoplay policy)
  if (ctx.state === "suspended") {
    ctx.resume();
  }

  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = type;
  osc.frequency.value = frequency;
  gain.gain.value = volume;

  // Fade out at the end to avoid clicks
  gain.gain.setValueAtTime(volume, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);

  osc.connect(gain);
  gain.connect(ctx.destination);

  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + duration);
}

function playSequence(
  notes: Array<{ freq: number; dur: number; delay: number }>,
  type: OscillatorType = "sine",
  volume: number = 0.3,
): void {
  const ctx = getAudioContext();
  if (!ctx || !isEnabled()) return;

  if (ctx.state === "suspended") ctx.resume();

  for (const note of notes) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = type;
    osc.frequency.value = note.freq;
    gain.gain.value = volume;
    gain.gain.setValueAtTime(volume, ctx.currentTime + note.delay);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + note.delay + note.dur);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(ctx.currentTime + note.delay);
    osc.stop(ctx.currentTime + note.delay + note.dur);
  }
}

const ALERT_SOUNDS: Record<AlertType, () => void> = {
  signal: () => {
    // Ascending 3-note chime (C5 → E5 → G5)
    playSequence([
      { freq: 523, dur: 0.15, delay: 0 },
      { freq: 659, dur: 0.15, delay: 0.12 },
      { freq: 784, dur: 0.25, delay: 0.24 },
    ], "sine", 0.25);
  },

  trade: () => {
    // Short confirmation double-beep
    playSequence([
      { freq: 880, dur: 0.08, delay: 0 },
      { freq: 1100, dur: 0.12, delay: 0.1 },
    ], "sine", 0.2);
  },

  stop_hit: () => {
    // Descending warning (G4 → D4 → A3)
    playSequence([
      { freq: 392, dur: 0.2, delay: 0 },
      { freq: 294, dur: 0.2, delay: 0.15 },
      { freq: 220, dur: 0.3, delay: 0.3 },
    ], "triangle", 0.3);
  },

  target_hit: () => {
    // Happy ascending (C5 → E5 → G5 → C6)
    playSequence([
      { freq: 523, dur: 0.12, delay: 0 },
      { freq: 659, dur: 0.12, delay: 0.1 },
      { freq: 784, dur: 0.12, delay: 0.2 },
      { freq: 1047, dur: 0.3, delay: 0.3 },
    ], "sine", 0.25);
  },

  order_rejected: () => {
    // Error buzz (low frequency)
    playSequence([
      { freq: 200, dur: 0.15, delay: 0 },
      { freq: 200, dur: 0.15, delay: 0.2 },
      { freq: 150, dur: 0.2, delay: 0.4 },
    ], "square", 0.15);
  },

  eod_close: () => {
    // Neutral bell
    playTone(660, 0.4, "sine", 0.2);
  },

  error: () => {
    // Low warning buzz
    playTone(180, 0.5, "square", 0.15);
  },
};

export function playAlert(type: AlertType): void {
  try {
    ALERT_SOUNDS[type]?.();
  } catch {
    // Audio not available — fail silently
  }
}
