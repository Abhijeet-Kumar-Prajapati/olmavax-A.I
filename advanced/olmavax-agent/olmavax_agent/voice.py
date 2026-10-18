"""
Olmavax Agent - Voice
====================
Speaks and listens, with graceful degradation at every layer.

**Speaking.**  ``pyttsx3`` if installed (fast, in-process), otherwise
Windows SAPI through PowerShell (always present on Windows, text is passed
as base64 so no quoting or encoding can corrupt it), otherwise it prints.

**Listening.**  ``speech_recognition`` with Google, then Vosk (fully
offline), then Whisper (local, slow but accurate), then typed input.  The
first one that imports wins and the choice is reported honestly.

The wake word loop exits the moment it hears ``exit`` / ``bus`` /
``band karo`` - that is the "bolane par band ho jata hai" behaviour.
"""

from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import VoiceConfig, get_config
from .events import BUS, Ev
from .logger import log_info, log_warn
from .nlu import get_nlu
from .utils import run_command, truncate

IS_WINDOWS = sys.platform.startswith("win")


# --------------------------------------------------------------------------
# Speech synthesis
# --------------------------------------------------------------------------


class Speaker:
    """Text to speech with three fallbacks."""

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.cfg = config or get_config().voice
        self._pyttsx3 = None
        self._engine_failed = False
        self.spoken_chars = 0

    # -- backend selection ---------------------------------------------
    def _ensure_engine(self) -> bool:
        if self._pyttsx3 is not None:
            return True
        if self._engine_failed:
            return False
        try:
            import pyttsx3

            self._pyttsx3 = pyttsx3.init()
            self._pyttsx3.setProperty("rate", self.cfg.tts_rate)
            self._pyttsx3.setProperty("volume", self.cfg.tts_volume)
            return True
        except Exception as exc:
            log_warn(f"pyttsx3 unavailable ({exc}); falling back to SAPI", "voice")
            self._engine_failed = True
            return False

    @property
    def backend(self) -> str:
        if self._ensure_engine():
            return "pyttsx3"
        if IS_WINDOWS and shutil.which("powershell"):
            return "windows-sapi"
        return "console"

    # -- speak ----------------------------------------------------------
    def speak(self, text: str) -> bool:
        """Say something. Returns True if audio was actually produced."""
        clean = (text or "").strip()
        if not clean or not self.cfg.speak_responses:
            return False
        clean = _speakable(clean)
        self.spoken_chars += len(clean)

        if self._ensure_engine():
            try:
                self._pyttsx3.say(clean)
                self._pyttsx3.runAndWait()
                BUS.emit(Ev.VOICE_STOP, {"chars": len(clean), "backend": "pyttsx3"}, "voice")
                return True
            except Exception as exc:
                log_warn(f"pyttsx3 failed ({exc}); trying SAPI", "voice")
                self._engine_failed = True

        if IS_WINDOWS and shutil.which("powershell"):
            # Base64 avoids every quoting and codepage problem.
            payload = base64.b64encode(clean.encode("utf-8")).decode("ascii")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$t=[System.Text.Encoding]::UTF8.GetString("
                f"[System.Convert]::FromBase64String('{payload}')); "
                f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Rate={max(-10, min(10, int(self.cfg.tts_rate) // 20 - 1))}; "
                f"$s.Volume={max(0, min(100, int(self.cfg.tts_volume * 100)))}; "
                "$s.Speak($t)"
            )
            code, _, _ = run_command(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=90,
            )
            if code == 0:
                BUS.emit(Ev.VOICE_STOP, {"chars": len(clean), "backend": "sapi"}, "voice")
                return True

        print(f"[olmavax_agent speaks] {clean}")
        return False

    def stop(self) -> None:
        if self._pyttsx3 is not None:
            try:
                self._pyttsx3.stop()
            except Exception:
                pass


def _speakable(text: str) -> str:
    """Strip things that sound wrong when read aloud."""
    import re

    text = re.sub(r"```.*?```", " code block ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#>|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Long monologues are tiring out loud; keep it to the first part.
    if len(text) > 700:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        trimmed = ""
        for sentence in sentences:
            if len(trimmed) + len(sentence) > 700:
                break
            trimmed += sentence + " "
        text = trimmed.strip() or text[:700]
    return text


# --------------------------------------------------------------------------
# Speech recognition
# --------------------------------------------------------------------------


@dataclass
class Listener:
    """Wraps whichever speech recognition backend imported successfully."""

    engine_name: str = "typed"
    _recogniser: Any = None
    _vosk_model: Any = None
    _whisper_model: Any = None
    detail: str = ""

    def __post_init__(self) -> None:
        self._setup()

    def _setup(self) -> None:
        cfg = get_config().voice

        if cfg.stt_engine in {"auto", "speech_recognition"}:
            try:
                import speech_recognition as sr

                self._recogniser = sr.Recognizer()
                self._recogniser.energy_threshold = cfg.mic_energy_threshold
                self._recogniser.dynamic_energy_threshold = True
                self.engine_name = "speech_recognition"
                self.detail = "Google speech API (needs internet)"
                return
            except ImportError:
                pass

        if cfg.stt_engine in {"auto", "vosk"}:
            try:
                import json as _json

                from vosk import KaldiRecognizer, Model

                self._vosk_model = Model(lang="en-in")
                self.engine_name = "vosk"
                self.detail = "fully offline, needs vosk + a downloaded model"
                self._vosk_helpers = (KaldiRecognizer, _json)
                return
            except ImportError:
                pass

        if cfg.stt_engine in {"auto", "whisper"}:
            try:
                import whisper

                self._whisper_model = whisper.load_model("base")
                self.engine_name = "whisper"
                self.detail = "fully offline, slow but accurate"
                return
            except ImportError:
                pass

        self.engine_name = "typed"
        self.detail = "no speech engine installed - type your commands instead"

    @property
    def can_listen(self) -> bool:
        return self.engine_name != "typed"

    def listen_once(self, timeout: float = 7.0, phrase_limit: float = 9.0) -> str:
        """Listen for one utterance. Returns text, or '' on failure."""
        cfg = get_config().voice

        if self.engine_name == "speech_recognition":
            return self._listen_sr(timeout, phrase_limit)
        if self.engine_name == "vosk":
            return self._listen_vosk(timeout)
        if self.engine_name == "whisper":
            return self._listen_whisper(timeout)
        try:
            return input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def _listen_sr(self, timeout: float, phrase_limit: float) -> str:
        import speech_recognition as sr

        cfg = get_config().voice
        try:
            with sr.Microphone() as source:
                source.dynamic_energy_threshold = True
                self._recogniser.adjust_for_ambient_noise(source, duration=0.4)
                print("  listening...")
                audio = self._recogniser.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
        except sr.WaitTimeoutError:
            return ""
        except Exception as exc:
            log_warn(f"microphone unavailable: {exc}", "voice")
            self.detail = f"microphone error: {exc}"
            return ""

        for attempt in range(2):
            try:
                if attempt == 0:
                    return self._recogniser.recognize_google(audio, language=cfg.language)
                return self._recognizer_transcribe(audio)
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as exc:
                log_warn(f"speech service error: {exc}", "voice")
                return ""
            except Exception:
                return ""
        return ""

    def _recognizer_transcribe(self, audio: Any) -> str:
        """Fallback recogniser path (Sphinx / pocketsphinx)."""
        import speech_recognition as sr

        try:
            return self._recogniser.recognize_sphinx(audio)
        except Exception:
            raise sr.UnknownValueError()

    def _listen_vosk(self, timeout: float) -> str:
        try:
            import json as _json
            import sounddevice as sd

            recogniser_cls, json_module = self._vosk_helpers
            recorder = sd.RawInputStream(samplerate=16000, channels=1, dtype="int16")
            model = self._vosk_model
            recogniser = recogniser_cls(model, 16000)
            pieces: List[str] = []
            start = time.time()
            with recorder:
                print("  listening...")
                while True:
                    data, _ = recorder.read(4096)
                    if recogniser.AcceptWaveform(data):
                        pieces.append(json_module.loads(recogniser.Result()).get("text", ""))
                    if pieces or time.time() - start > timeout:
                        break
            return " ".join(p for p in pieces if p).strip()
        except Exception as exc:
            log_warn(f"vosk listen failed: {exc}", "voice")
            return ""

    def _listen_whisper(self, timeout: float) -> str:
        try:
            import tempfile

            import numpy as np
            import sounddevice as sd
            import whisper

            print("  listening...")
            recorder = sd.InputStream(samplerate=16000, channels=1)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                path = tmp.name
            with recorder:
                frames = sd.rec(int(timeout * 16000), samplerate=16000, channels=1)
                sd.wait()
            audio = np.squeeze(frames) * (1 / 32768.0)
            with whisper.audio.open(path) as handle:
                result = self._whisper_model.transcribe(handle)
            os.unlink(path)
            return str(result.get("text", "")).strip()
        except Exception as exc:
            log_warn(f"whisper listen failed: {exc}", "voice")
            return ""

    def info(self) -> Dict[str, str]:
        return {"engine": self.engine_name, "detail": self.detail}


# --------------------------------------------------------------------------
# Voice assistant
# --------------------------------------------------------------------------


class VoiceAssistant:
    """Ties the listener, speaker and brain together."""

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.cfg = config or get_config().voice
        self.speaker = Speaker(self.cfg)
        self.listener = Listener()
        self.listening = False
        self.last_voice = 0.0

    # -- one shot -------------------------------------------------------
    def ask(self, prompt: str = "") -> str:
        """Listen once and return what was heard."""
        heard = self.listener.listen_once(
            self.cfg.listen_timeout, self.cfg.phrase_time_limit
        )
        self.last_voice = time.time()
        if heard:
            BUS.emit(Ev.VOICE_HEARD, {"text": truncate(heard, 120)}, "voice")
        return heard

    def say(self, text: str) -> None:
        if self.cfg.speak_responses:
            self.speaker.speak(text)

    # -- continuous -----------------------------------------------------
    def loop(self, brain: Any, max_turns: int = 0) -> Dict[str, Any]:
        """
        Wake-word listening loop.

        Exits on ``exit`` / ``bus`` / ``band karo``, on Ctrl+C, or after
        ``max_turns`` if given.
        """
        nlu = get_nlu()
        self.listening = True
        turns = 0
        heard_count = 0
        BUS.emit(Ev.VOICE_START, {"backend": self.listener.engine_name}, "voice")

        print("\n" + "=" * 62)
        print(f"  {get_config().name.upper()} IS LISTENING")
        print(f"  speech engine : {self.listener.info()['engine']} ({self.listener.info()['detail']})")
        print(f"  wake word     : {', '.join(self.cfg.wake_words)}")
        print("  say 'exit' or 'bus' to close me")
        print("=" * 62 + "\n")

        try:
            while self.listening:
                if max_turns and turns >= max_turns:
                    break
                raw = self.listener.listen_once(
                    self.cfg.listen_timeout, self.cfg.phrase_time_limit
                )
                if not raw:
                    continue
                heard_count += 1

                text, woke = nlu.strip_wake_word(raw)
                if self.cfg.require_wake_word and not woke:
                    print(f"  (heard '{truncate(raw, 60)}' - waiting for the wake word)")
                    continue
                if not text:
                    continue

                print(f"you> {text}")
                reply = brain.think(text, source="voice")
                turns += 1
                print(f"olmavax_agent> {reply.text}\n")
                self.say(reply.text)

                if reply.intent == "shutdown":
                    break
        except KeyboardInterrupt:
            print("\n  interrupted - powering down")
        finally:
            self.listening = False
            self.speaker.stop()
            BUS.emit(Ev.VOICE_STOP, {"turns": turns, "heard": heard_count}, "voice")

        return {"turns": turns, "utterances": heard_count, "stopped": True}

    # -- diagnostics ----------------------------------------------------
    def report(self) -> str:
        lines = ["Voice capability", "-----------------"]
        lines.append(f"  speech out : {self.speaker.backend}")
        lines.append(f"  speech in  : {self.listener.info()['engine']} - {self.listener.info()['detail']}")
        lines.append(f"  speak all  : {'yes' if self.cfg.speak_responses else 'no'}")
        lines.append(f"  wake word  : {', '.join(self.cfg.wake_words)}")
        lines.append(f"  required   : {'yes' if self.cfg.require_wake_word else 'no'}")
        lines.append(f"  language   : {self.cfg.language}")
        mic = _microphone_present()
        lines.append(f"  microphone : {'detected' if mic else 'not detected'}")
        return "\n".join(lines)

    def info(self) -> Dict[str, Any]:
        return {
            "speak_backend": self.speaker.backend,
            "listen_backend": self.listener.info(),
            "wake_words": self.cfg.wake_words,
            "require_wake_word": self.cfg.require_wake_word,
            "speak_responses": self.cfg.speak_responses,
            "language": self.cfg.language,
            "microphone": _microphone_present(),
            "listening": self.listening,
        }


def _microphone_present() -> bool:
    try:
        import speech_recognition as sr

        return sr.Microphone() is not None
    except Exception:
        return False


_ASSISTANT: Optional[VoiceAssistant] = None


def get_voice() -> VoiceAssistant:
    global _ASSISTANT
    if _ASSISTANT is None:
        _ASSISTANT = VoiceAssistant()
    return _ASSISTANT