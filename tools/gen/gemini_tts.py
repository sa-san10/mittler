# Mittler（写したときの名前は claude-cut）の写し（元：作者の制作のワークスペースの slideshow-video\gemini_tts.py、2026-10-21）。読み辞書を作品ごとに・鍵の読み出しを同じフォルダから、だけ変えた。
"""Generate a WAV with Gemini 3.8 TTS using only Python's standard library."""

import argparse
import base64
import binascii
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import wave
from pronunciation import load_dictionary, replace_readings


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-3.8-flash-tts"
VOICES = """Zephyr Puck Charon Kore Fenrir Leda Orus Aoede Callirrhoe Autonoe
Enceladus Iapetus Umbriel Algieba Despina Erinome Algenib Rasalgethi Laomedeia
Achernar Alnilam Schedar Gacrux Pulcherrima Achird Zubenelgenubi Vindemiatrix
Sadachbia Sadaltager Sulafat""".split()


class TTSError(Exception):
    pass


SECRETS_DIR = ROOT  # Mittler：鍵の読み出し（credman_secret.py）も同じフォルダにある。資格情報マネージャーの ps:GEMINI_API_KEY


def load_key(env_file):
    """Prefer the requested local file, then the environment, then Windows Credential Manager."""
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, value = line.partition("=")
            if separator and name.strip() == "GEMINI_API_KEY":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                else:
                    value = value.split(" #", 1)[0].rstrip()
                if value:
                    return value
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key and (SECRETS_DIR / "credman_secret.py").is_file():
        sys.path.insert(0, str(SECRETS_DIR))
        try:
            from credman_secret import get_secret
        finally:
            sys.path.remove(str(SECRETS_DIR))
        key = get_secret("GEMINI_API_KEY", env_first=False) or ""
    if not key:
        raise TTSError("GEMINI_API_KEY is missing. Set-Secret -Name GEMINI_API_KEY (CredMan vault).")
    return key


def make_payload(text, style, voice, dictionary=None):
    # Mittler：読み辞書は作品ごと（<作品>/pronunciation.json、無ければ読み替えない）
    if dictionary and Path(dictionary).is_file():
        text, _ = replace_readings(text, load_dictionary(dictionary))
    part = {"text": text}
    if style:
        part["speech_metadata"] = {"style": style}
    return {
        "contents": [{"role": "user", "parts": [part]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"voice": voice}},
        },
    }


def request_audio(key, model, payload, timeout):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print response bodies or request headers, which could contain secrets.
        hints = {
            400: "Check the text, voice and model parameters.",
            401: "Check your API key.",
            403: "Check your API key, project permissions and API access.",
            404: "The selected model is unavailable for this endpoint/project.",
            429: "Quota or rate limit reached. Check billing/quota before retrying.",
        }
        raise TTSError(f"Gemini HTTP {exc.code}. " + hints.get(exc.code, "API request failed.")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TTSError("Network request failed or timed out; no automatic retry was made.") from None
    except (ValueError, UnicodeError):
        raise TTSError("Gemini returned an invalid JSON response.") from None


def extract_wav(response):
    candidates = response.get("candidates") or []
    if not candidates:
        raise TTSError("Gemini returned no audio candidate (possibly blocked input).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    chunks = []
    for part in parts:
        inline = part.get("inlineData") or {}
        if inline.get("data"):
            try:
                chunks.append(base64.b64decode(inline["data"], validate=True))
            except (ValueError, binascii.Error):
                raise TTSError("Invalid base64 audio in the response.") from None
    if len(chunks) != 1:
        raise TTSError("Expected one complete WAV audio part; output was not saved.")
    data = chunks[0]
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            expected_bytes = frames * audio.getnchannels() * audio.getsampwidth()
            if not frames or not rate or len(audio.readframes(frames)) != expected_bytes:
                raise TTSError("Empty or truncated WAV audio returned by Gemini.")
            duration = frames / rate
    except (wave.Error, EOFError):
        raise TTSError("Response was not a supported PCM WAV; output was not saved.") from None
    return data, duration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Text to speak verbatim")
    source.add_argument("--text-file", type=Path, help="UTF-8 narration text file")
    parser.add_argument("--style", default="", help="Voice quality, emotion, pace and delivery instructions")
    parser.add_argument("--voice", default="Kore", help="Voice name or voice ID (default: Kore)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "narration.wav")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing WAV")
    parser.add_argument("--dictionary", type=Path, help="読み辞書（作品の pronunciation.json）")
    parser.add_argument("--list-voices", action="store_true", help="List the 30 built-in names without an API call")
    parser.add_argument("--check-key", action="store_true", help="Check local key presence only; do not contact Gemini")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and key presence without contacting Gemini")
    args = parser.parse_args()
    try:
        if args.list_voices:
            print("\n".join(VOICES))
            return 0
        if args.check_key:
            load_key(args.env_file)
            print("GEMINI_API_KEY is configured (not authenticated with Gemini).")
            return 0
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise TTSError("--timeout must be a positive finite number.")
        if not re.fullmatch(r"gemini-3\.8-flash(?:-lite)?-tts", args.model):
            raise TTSError("Supported models: gemini-3.8-flash-tts, gemini-3.8-flash-lite-tts.")
        text = args.text_file.read_text(encoding="utf-8-sig") if args.text_file else args.text
        if not text or not text.strip():
            raise TTSError("Provide nonempty --text or --text-file.")
        if not args.voice.strip():
            raise TTSError("--voice cannot be empty.")
        output = args.out.resolve()
        if output.suffix.lower() != ".wav":
            raise TTSError("--out must have a .wav extension.")
        if output.exists() and not args.overwrite:
            raise TTSError("Output already exists; choose another filename or pass --overwrite.")
        key = load_key(args.env_file)
        payload = make_payload(text, args.style, args.voice, args.dictionary)
        if args.dry_run:
            print("Inputs and local key presence checked. No API request made.")
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        data, duration = extract_wav(request_audio(key, args.model, payload, args.timeout))
        with output.open("wb" if args.overwrite else "xb") as handle:
            handle.write(data)
        print(f"Saved: {output}\nDuration: {duration:.2f} seconds")
        return 0
    except (TTSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("Error: Could not read/write a local file; check its path, encoding and permissions.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
