#!/usr/bin/env python3
"""
## st-speak — Render a story into spoken audio (MP3)

Converts the spoken-text field of a story from a .json container into an MP3
file using a local Piper TTS server.

```
st-speak subject.json               # render story 1 → subject.mp3
st-speak -s 3 subject.json          # render story 3
st-speak --source fact subject.json # read the fact-check report aloud
st-speak --voice en_US-ryan-high subject.json  # override voice for this render
```

Setup:
  Set TTS_HOST, TTS_PORT, and TTS_VOICE in .env, then start a local Piper
  server.  Use st-admin to set the default voice (--set-tts-voice or
  interactive V key).  Use st-voice to browse all available Piper voice
  names and download the ONNX model files needed by the server.

Required .env keys: TTS_HOST  TTS_PORT  TTS_VOICE

TTS is optional — without it, use requirements-no-tts.txt and Python 3.10+.
With TTS, Python 3.10–3.13 all work (soundfile and yakyak have wheels for
every supported Python version on macOS ARM and Linux).

See also: st-admin (set default TTS voice)
          st-voice  (browse / download Piper voice models)

Options: -s story  --source {text,fact}  --voice model  -v  -q
"""

import argparse
import asyncio
import json
import os
import sys
from mmd_startup import load_cross_env, require_config

try:
    from yakyak import is_server_online
    from yakyak import piper_tts_server
except ImportError:
    print("Error: st-speak requires TTS packages.  "
          "Run: pipx install --force \"cross-st[tts]\"",
          file=sys.stderr)
    sys.exit(1)

from mmd_for_speaking import for_speaking
from mmd_process_report import remove_markdown


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-speak',
        description='Render a story into spoken audio, an mp3 file.')
    parser.add_argument('json_file', type=str,
                        help='Path to the JSON file', metavar='file.json')
    parser.add_argument('-s', '--story', type=int, default=1,
                        help='Story to convert (integer), default 1')
    parser.add_argument('--source', type=str,
                        choices=['text', 'fact'], default='text',
                        help="Select text source. Options: 'text' (default) or 'fact'.")
    parser.add_argument('--voice', type=str,
                        help='Onnx voice model')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')

    args = parser.parse_args()
    file_prefix = args.json_file.rsplit('.', 1)[0]  # Split from the right, only once
    file_json = file_prefix + ".json"
    file_mp3 = file_prefix + ".mp3"

    # Use realpath to get the actual path of the script
    load_cross_env()

    try:
        if args.json_file is not None and not args.json_file.lower().endswith(".json"):
            print(f"Error: The file {args.json_file} needs to be {file_prefix}.json.")
            sys.exit(1)
        # Process the JSON file
        if not os.path.isfile(file_json):
            print(f"Error: The file {args.json_file} does not exist.")
            sys.exit(1)

        with open(file_json, 'r') as file:
            main_container = json.load(file)
            if args.source == 'text':
                tts_source = main_container["story"][args.story]["spoken"]
            elif "fact" in main_container["story"][args.story]:
                fact = main_container["story"][args.story]["fact"]
                step1 = for_speaking(fact)
                tts_source = remove_markdown(step1)
            else:
                tts_source = "This story does not have any fact check data"

    except json.JSONDecodeError:
        print(f"Error: The file {file_json} contains invalid JSON.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

    host = os.getenv("TTS_HOST")
    port = int(os.getenv("TTS_PORT"))
    voice = os.getenv("TTS_VOICE")
    if args.voice is not None:  # TODO add support for host and port
        voice = args.voice  # TODO test command line for voice, robust error checking

    if not is_server_online(host, port):
        print(f"TTS host {host}:{port} is offline")
    else:
        if args.verbose:
            print(f"TTS host {host}:{port} voice:{voice}")
        if not args.quiet:
            print(f"Rendering audio")
        asyncio.run(
            piper_tts_server(host, port, tts_source, file_mp3, "mp3", voice)
        )
        if not args.quiet:
            print(f"Audio mp3 render complete")


if __name__ == "__main__":
    main()
