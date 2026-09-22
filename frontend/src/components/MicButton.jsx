import { useRef, useState } from "react";
import { LoaderCircle, Mic, MicOff } from "lucide-react";

import { useLanguage } from "../i18n/LanguageContext";
import { recordAudio, startBrowserRecognition, transcribeWithBhashini, voiceProvider } from "../voice";

// Fills only the caller's transcript target (the free-text box), never a
// structured field directly — the user sees and can correct the transcript
// there before "Fill fields from my description" runs profile extraction.
export default function MicButton({ lang, onTranscript }) {
  const { t } = useLanguage();
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recorderRef = useRef(null);
  const recognitionRef = useRef(null);

  async function start() {
    setError("");

    if (voiceProvider() === "bhashini") {
      try {
        recorderRef.current = await recordAudio();
        setRecording(true);
      } catch (err) {
        setError(err.message);
      }
      return;
    }

    recognitionRef.current = startBrowserRecognition(lang, {
      onResult: (transcript) => {
        onTranscript(transcript);
        setRecording(false);
      },
      onError: (err) => {
        setError(err.message);
        setRecording(false);
      },
      onEnd: () => setRecording(false),
    });

    if (recognitionRef.current) setRecording(true);
  }

  async function stop() {
    if (voiceProvider() !== "bhashini") {
      recognitionRef.current?.stop();
      setRecording(false);
      return;
    }

    const recorder = recorderRef.current;
    recorderRef.current = null;

    if (!recorder) {
      setRecording(false);
      return;
    }

    setRecording(false);
    setBusy(true);
    recorder.stop();

    try {
      const blob = await recorder.blob;
      const transcript = await transcribeWithBhashini(blob, lang);
      onTranscript(transcript);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-flex flex-col items-start gap-2">
      <button
        type="button"
        className="btn-secondary"
        disabled={busy}
        aria-pressed={recording}
        onClick={recording ? stop : start}
      >
        {busy ? (
          <>
            <LoaderCircle size={16} className="animate-spin" />
            {t("voice.transcribing")}
          </>
        ) : recording ? (
          <>
            <MicOff size={16} /> {t("voice.stop")}
          </>
        ) : (
          <>
            <Mic size={16} /> {t("voice.mic")}
          </>
        )}
      </button>
      {error && (
        <p className="text-sm leading-6 text-red-700">
          {t("voice.error", { message: error })}
        </p>
      )}
    </div>
  );
}
