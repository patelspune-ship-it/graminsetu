// Voice layer: Bhashini (backend ULCA pipeline) when configured, browser
// Web Speech API otherwise. Selected by VITE_VOICE_PROVIDER so the mic/
// listen buttons still demo without a Bhashini key.
//
// Deliberately separate from api.js: that helper always sends/receives
// JSON, while /api/voice/speak returns raw audio bytes and the browser
// provider never touches the backend at all.

const BROWSER_LANG = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

export function voiceProvider() {
  return import.meta.env.VITE_VOICE_PROVIDER === "bhashini" ? "bhashini" : "browser";
}

function browserLang(lang) {
  return BROWSER_LANG[lang] || "en-IN";
}

async function readErrorMessage(response) {
  const body = await response.json().catch(() => null);
  return body?.error?.message || `Request failed (${response.status}).`;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("Could not read the recording."));
    reader.readAsDataURL(blob);
  });
}

// --- Recording (Bhashini ASR path) -----------------------------------

export async function recordAudio() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone access is not supported in this browser.");
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks = [];

  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });

  const blob = new Promise((resolve) => {
    recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop());
      resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
    });
  });

  recorder.start();

  return { stop: () => recorder.stop(), blob };
}

export async function transcribeWithBhashini(audioBlob, lang) {
  const audio_base64 = await blobToBase64(audioBlob);

  const response = await fetch("/api/voice/transcribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_base64, lang }),
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.transcript;
}

// --- Browser Web Speech ASR --------------------------------------------

export function browserAsrSupported() {
  return typeof window !== "undefined" && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

// Returns the live recognition instance (so the caller can stop it early),
// or null if this browser has no Web Speech ASR support.
export function startBrowserRecognition(lang, { onResult, onError, onEnd }) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    onError(new Error("Speech recognition is not supported in this browser."));
    return null;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = browserLang(lang);
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => onResult(event.results[0][0].transcript);
  recognition.onerror = (event) => onError(new Error(event.error || "Speech recognition failed."));
  recognition.onend = () => onEnd?.();

  recognition.start();
  return recognition;
}

// --- TTS -----------------------------------------------------------------

async function speakWithBhashini(text, lang) {
  const response = await fetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang }),
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);

  try {
    await audio.play();
  } finally {
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
  }
}

function speakWithBrowser(text, lang) {
  if (!("speechSynthesis" in window)) {
    return Promise.reject(new Error("Speech playback is not supported in this browser."));
  }

  return new Promise((resolve, reject) => {
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = browserLang(lang);
    utterance.onend = () => resolve();
    utterance.onerror = (event) => reject(new Error(event.error || "Speech playback failed."));

    window.speechSynthesis.speak(utterance);
  });
}

export async function synthesizeAndPlay(text, lang) {
  if (voiceProvider() === "bhashini") {
    return speakWithBhashini(text, lang);
  }
  return speakWithBrowser(text, lang);
}
