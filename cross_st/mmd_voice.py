import requests

# Base URL for Piper voice models
# BASE_URL = "https://github.com/rhasspy/piper/releases/latest/download"
# URL of the Piper VOICES.md file
# VOICES_MD_URL = "https://github.com/rhasspy/piper/blob/master/VOICES.md"
VOICES_MD_URL = "https://raw.githubusercontent.com/rhasspy/piper/master/VOICES.md"
# URL of the voices.json file in the Piper repository
VOICES_JSON_URL = "https://raw.githubusercontent.com/rhasspy/piper/master/src/python_run/piper/voices.json"


def get_onyx_voice_list(url=VOICES_JSON_URL):

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch voices.json: {response.status_code}")

    voices_data = response.json()

    # Extract and filter voice model keys
    voices = []
    for voice in voices_data.keys():
        if voice.startswith("en_GB") or voice.startswith("en_US"):
            voices.append(voice)

    return voices


def get_onyx_voice_list_best_few():
    text = f"""
en_US-amy-medium
en_US-ryan-high 
en_US-libritts-high
en_US-lessac-high
en_GB-aru-medium
"""
    return text.strip().split()


def get_onyx_voice_list_static():
    text = f"""
en_US-amy-low
en_US-amy-medium
en_US-arctic-medium
en_US-bryce-medium
en_US-danny-low
en_US-hfc_female-medium
en_US-hfc_male-medium
en_US-joe-medium
en_US-john-medium
en_US-kathleen-low
en_US-kristin-medium
en_US-kusal-medium
en_US-l2arctic-medium
en_US-lessac-low
en_US-lessac-medium
en_US-lessac-high
en_US-libritts-high
en_US-libritts_r-medium
en_US-ljspeech-medium
en_US-ljspeech-high
en_US-norman-medium
en_US-ryan-low
en_US-ryan-medium
en_US-ryan-high 
"""
    return text.strip().split()


def get_latest_piper_release():
    """Fetches the latest Piper release tag from GitHub."""
    url = "https://api.github.com/repos/rhasspy/piper/releases/latest"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch latest Piper release: {response.status_code}")

    return response.json().get("tag_name", "")


# Hugging Face base URL for Piper voices
BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


def get_onyx_voice_curl(voices=""):
    """Generates curl commands for Piper voices from Hugging Face."""

    if voices == "":
        voices = get_onyx_voice_list()

    # Define BASE_URL once in the output
    commands = [f'BASE_URL="{BASE_URL}"\n']

    for voice in voices:
        # Extract language, region, and speaker from voice name
        parts = voice.split("-")  # Example: en_US-amy-medium
        if len(parts) < 3:
            continue  # Skip malformed voice names

        language, speaker, size = parts[0], parts[1], parts[2]

        model_url = f"$BASE_URL/en/{language}/{speaker}/{size}/{voice}.onnx"
        config_url = f"$BASE_URL/en/{language}/{speaker}/{size}/{voice}.onnx.json"

        commands.append(f'curl -LO "{model_url}"')
        commands.append(f'curl -LO "{config_url}"')

    return commands


def get_onyx_voice_curl_static():
    text = f"""
    BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

curl -LO "$BASE_URL/en/en_GB/alan/low/en_GB-alan-low.onnx"
curl -LO "$BASE_URL/en/en_GB/alan/low/en_GB-alan-low.onnx.json"
curl -LO "$BASE_URL/en/en_GB/alan/medium/en_GB-alan-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/alba/medium/en_GB-alba-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/aru/medium/en_GB-aru-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/aru/medium/en_GB-aru-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx.json"
curl -LO "$BASE_URL/en/en_GB/southern_english_female/low/en_GB-southern_english_female-low.onnx"
curl -LO "$BASE_URL/en/en_GB/southern_english_female/low/en_GB-southern_english_female-low.onnx.json"
curl -LO "$BASE_URL/en/en_GB/vctk/medium/en_GB-vctk-medium.onnx"
curl -LO "$BASE_URL/en/en_GB/vctk/medium/en_GB-vctk-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/amy/low/en_US-amy-low.onnx"
curl -LO "$BASE_URL/en/en_US/amy/low/en_US-amy-low.onnx.json"
curl -LO "$BASE_URL/en/en_US/amy/medium/en_US-amy-medium.onnx"
curl -LO "$BASE_URL/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/arctic/medium/en_US-arctic-medium.onnx"
curl -LO "$BASE_URL/en/en_US/arctic/medium/en_US-arctic-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/danny/low/en_US-danny-low.onnx"
curl -LO "$BASE_URL/en/en_US/danny/low/en_US-danny-low.onnx.json"
curl -LO "$BASE_URL/en/en_US/joe/medium/en_US-joe-medium.onnx"
curl -LO "$BASE_URL/en/en_US/joe/medium/en_US-joe-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/kathleen/low/en_US-kathleen-low.onnx"
curl -LO "$BASE_URL/en/en_US/kathleen/low/en_US-kathleen-low.onnx.json"
curl -LO "$BASE_URL/en/en_US/kusal/medium/en_US-kusal-medium.onnx"
curl -LO "$BASE_URL/en/en_US/kusal/medium/en_US-kusal-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/l2arctic/medium/en_US-l2arctic-medium.onnx"
curl -LO "$BASE_URL/en/en_US/l2arctic/medium/en_US-l2arctic-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/lessac/high/en_US-lessac-high.onnx"
curl -LO "$BASE_URL/en/en_US/lessac/high/en_US-lessac-high.onnx.json"
curl -LO "$BASE_URL/en/en_US/lessac/low/en_US-lessac-low.onnx"
curl -LO "$BASE_URL/en/en_US/lessac/low/en_US-lessac-low.onnx.json"
curl -LO "$BASE_URL/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
curl -LO "$BASE_URL/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
curl -LO "$BASE_URL/en/en_US/libritts/high/en_US-libritts-high.onnx"
curl -LO "$BASE_URL/en/en_US/libritts/high/en_US-libritts-high.onnx.json"
curl -LO "$BASE_URL/en/en_US/ryan/high/en_US-ryan-high.onnx"
curl -LO "$BASE_URL/en/en_US/ryan/high/en_US-ryan-high.onnx.json"
curl -LO "$BASE_URL/en/en_US/ryan/low/en_US-ryan-low.onnx"
curl -LO "$BASE_URL/en/en_US/ryan/low/en_US-ryan-low.onnx.json"
curl -LO "$BASE_URL/en/en_US/ryan/medium/en_US-ryan-medium.onnx"
curl -LO "$BASE_URL/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json"
    """
    return text.strip()
