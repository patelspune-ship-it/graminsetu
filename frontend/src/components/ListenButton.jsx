import { useState } from "react";
import { LoaderCircle, Volume2 } from "lucide-react";

import { useLanguage } from "../i18n/LanguageContext";
import { synthesizeAndPlay } from "../voice";

// Reads `text` aloud in `lang` (defaults to the selected UI language) via
// the shared voice layer (Bhashini or browser Web Speech, whichever
// VITE_VOICE_PROVIDER selects).
export default function ListenButton({ text, lang }) {
  const { t, language } = useLanguage();
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");

  async function handleClick() {
    setError("");
    setPlaying(true);
    try {
      await synthesizeAndPlay(text, lang || language);
    } catch (err) {
      setError(err.message);
    } finally {
      setPlaying(false);
    }
  }

  return (
    <div className="inline-flex flex-col items-start gap-2">
      <button
        type="button"
        className="btn-secondary"
        disabled={playing || !text}
        onClick={handleClick}
      >
        {playing ? (
          <>
            <LoaderCircle size={16} className="animate-spin" />
            {t("voice.playing")}
          </>
        ) : (
          <>
            <Volume2 size={16} /> {t("voice.listen")}
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
