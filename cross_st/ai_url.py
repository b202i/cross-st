# Sorry, no AI here
import os
import json
import hashlib
import requests
import sys

AI_MAKE = "url"
AI_MODEL = "bs4"


def get_url_cached_response(tweet_id, verbose=False, use_cache=False):

    url = f"https://api.twitter.com/2/tweets/{tweet_id}"
    headers = get_url_headers()

    if not use_cache:
        response = requests.get(url, headers=headers)
        json_str = json.dumps(response)  # Force structure reorganization
        json_response = json.loads(json_str)
        return json_response, False  # Not cached
    else:
        # Convert param to a string for hashing
        param = {
            "tweet_id": tweet_id,
            "headers": headers,
            "url": url,
        }
        param_str = json.dumps(param, sort_keys=True)
        md5_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()

        # Construct the cache file path
        cache_dir = os.path.expanduser("~/.cross_api_cache")
        cache_file = os.path.join(cache_dir, f"{md5_hash}.json")

        # Check if the response is already in cache
        if os.path.exists(cache_file):
            if verbose:
                print(f"api_cache: Using cache_file: {cache_file}")
            with open(cache_file, 'r') as f:
                return json.load(f), True  # Cached
        else:
            if verbose:
                print("api_cache: cache miss, submitting API request")

            # If not in cache, fetch the response
            response = requests.get(url, headers=headers)
            if (status_code := response["status_code"]) != 200:
                print(f"x.com response failed: {status_code}")
                sys.exit(1)
            json_str = json.dumps(response)  # Force structure reorganization
            json_response = json.loads(json_str)

            # Save to cache
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
                if verbose:
                    print(f"api_cache: api_cache/ dir created: {cache_dir}")

            try:
                with open(cache_file, 'w') as f:
                    json.dump(json_response, f)
                    if verbose:
                        print(f"api_cache: file created: {cache_file}")
            except Exception as e:
                print(f"api_cache: file write error: {str(e)}")

            return json_response, False  # Fresh API call, not cached


def get_url_headers():
    x_bearer_token = os.environ.get('X_COM_BEARER_TOKEN')
    headers = {"Authorization": f"Bearer {x_bearer_token}"}
    return headers


def get_title(data):
    title = data.get("title")
    return title


def get_story(data):
    text = data.get("text")
    return text


def get_ai_tag():
    return "\n\ncross:" + json.dumps(
        {"make": AI_MAKE, "model": AI_MODEL})
