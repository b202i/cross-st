import json
import re

global_verbose = False
DEBUG = False


def add_mp3_player_top(markdown_content, mp3_filename, mp3_url):
    """Add an audio player link to the very top of the post content. Return the updated content."""

    # Create the audio player link in Discourse markdown format.
    audio_link = f"![{mp3_filename}|audio]({mp3_url})\n\n"

    # Prepend the audio link at the top of the content.
    return audio_link + markdown_content


def add_mp3_player(markdown_content, mp3_filename, mp3_url):
    """Skip down after the title and add an audio player link
    to the post content. Return the updated content."""
    # Create the audio player link in Discourse markdown format.
    audio_link = f"![{mp3_filename}|audio]({mp3_url})\n"

    # Split the content into lines.
    lines = markdown_content.splitlines()
    new_lines = []
    inserted = False

    # Look for the first blank line (after the title block) to insert the audio link.
    for line in lines:
        new_lines.append(line)
        if not line.strip() and not inserted:
            new_lines.append(audio_link)
            inserted = True

    # If no blank line was found, append the audio link at the end.
    if not inserted:
        new_lines.append("")
        new_lines.append(audio_link)

    return "\n".join(new_lines)


def clean_for_platform(markdown, mp3_url=None):
    """Remove Discourse-specific media syntax from story markdown before posting
    to non-Discourse platforms (GitHub Gist, Bluesky, Reddit, X, etc.).

    - Strips  ![file.mp3|audio](url)  — Discourse audio player tag (|audio is Discourse-only)
    - Leaves  ![alt](url)  image tags intact — external PNG URLs render on most platforms
    - Optionally appends a plain audio link if mp3_url is provided

    Args:
        markdown (str): story_markdown from the JSON container
        mp3_url (str|None): Discourse-hosted MP3 URL, or None if no audio

    Returns:
        str: cleaned markdown safe for non-Discourse platforms
    """
    # Remove Discourse audio player embeds — the |audio suffix is Discourse-only BBCode
    cleaned = re.sub(r'!\[[^\]]*\|audio\]\([^)]*\)\n?', '', markdown)

    # Append a plain audio link if we have one
    if mp3_url:
        cleaned = cleaned.rstrip() + f'\n\n🎧 [Audio version]({mp3_url})\n'

    return cleaned


def apply_patterns(text, i):
    global global_verbose
    # Regex Notes:
    # \s* allows for optional whitespace.
    # [0-9]+ matches one or more digits for numbers like 1, 2, etc.
    # \.\s* matches a period followed by optional whitespace for patterns like "1. Headline:".
    patterns = [
        # Story 1, **Headline:**
        r'Story\s*[0-9]+,\s*\*\*Headline:\*\*',

        # **1. Headline:
        r'\*\*[0-9]+\.\s*Headline:',

        # ### **Headline:**
        r'###\s*\*\*Headline:\*\*',

        # **Headline:**
        r'\*\*Headline:\*\*',
    ]

    matched_pattern = None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            text = re.sub(pattern, f"Story {i}, ", text, flags=re.IGNORECASE)
            matched_pattern = pattern
            break  # Stop after the first match found, if you want to match all, remove this break

    if DEBUG:
        if matched_pattern:
            print(f"A match was found for pattern: {matched_pattern}")
        else:
            print("No pattern matched.")

    return text


def process_report(content, verbose=False):
    global global_verbose
    global_verbose = verbose
    # Process each story
    stories = re.split(r'\n---\n', content)
    processed_text = []
    references_json = []

    for i, story in enumerate(stories, 1):
        # Replace headline - multiple formats
        # pattern = r'###(?: \d+\.)? \*\*Headline:\*\* (.+?)'
        # pattern = r'###?(?: \d+\.)? *\*\*Headline:\*\* *(.+?)(?:\n|$)'
        # pattern = r'(?:###? *|)(\*\*Headline:\*\*|\*\*[0-9]+\. Headline:)(.+?)(?:\n|$)'
        # story = re.sub(pattern, f"Story {i}, \\1", story)
        story = apply_patterns(story, i)

        # Replace other bold markers
        replacements = {
            '\n\n**Summary:**': '.\n\n',  # Use a . after headline for voice pause
            '**Details:**': 'In detail,',
            '**Quotes:**': 'Quoting from the story,',
            '**Impact:**': 'The impact of this is,',
            '**Speculation:**': 'Looking forward,',
            '**Reference:**': '',
        }
        for key, value in replacements.items():
            story = story.replace(key, value)

        # Extract reference
        ref_match = re.search(r'```json\n(.+?)\n```', story, re.DOTALL)
        if ref_match:
            ref = json.loads(ref_match.group(1))
            references_json.append(ref)
            story = re.sub(r'```json\n(.+?)\n```', '', story, flags=re.DOTALL)

        # Remove the "Follow on X:" section
        story = re.sub(r'\*\*Follow on X:\*\*.*', '', story, flags=re.DOTALL)
        processed_text.append(story.strip() + '\n\n')

    processed_text_str = '\n'.join(processed_text)

    return processed_text_str, references_json


def remove_markdown(text):
    # Remove inline Markdown elements like **bold**, *italic*, `code`, etc.
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)  # italic
    text = re.sub(r'`([^`]+)`', r'\1', text)  # inline code
    text = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', text)  # links
    text = re.sub(r'#+', '', text)  # headers
    text = re.sub(r'!\[[^]]*\]\([^)]+\)', '', text)  # images
    # text = re.sub(r'^\s*[-*+] ', '', text, flags=re.MULTILINE)  # lists
    text = re.sub(r'^> ', '', text, flags=re.MULTILINE)  # blockquotes
    text = re.sub(r'^```.*```', '', text, flags=re.DOTALL)  # code blocks
    text = re.sub(r'\n{3,}', '\n\n', text)  # match 2 or more newlines
    text = re.sub(r'\*{2,}', '', text)  # match 2 or more *
    text = re.sub(r'/n', '', text)  # remove all '/n' occurrences

    return text.strip()


def clean_newlines_preserve_paragraphs(text):
    """
    Clean up newline characters in a string while preserving paragraph breaks.

    :param text: The string text with newline characters.
    :return: A string where single newlines are replaced with spaces,
             but double newlines (paragraph breaks) are preserved.

    Numbered list items (lines that begin with ``N.`` or ``N.  ``) are
    promoted to paragraph breaks *before* the single-newline collapse so
    that list-formatted AI responses (e.g. Gemini returning 10 claims
    each on their own line) produce the same per-claim segmentation as
    prose-formatted responses.  Without this step every claim ends up in
    a single merged paragraph and fact-checking treats all 10 as one unit.
    """
    # Normalize line endings
    text = text.replace('\r\n', '\n')

    # Promote numbered list items to paragraph boundaries.
    # Match a single \n (not already preceded by \n) that is immediately
    # followed by one or more digits, a period, and 1-2 spaces — the
    # standard Markdown ordered-list marker pattern.
    text = re.sub(r'(?<!\n)\n(\d+\.\s)', r'\n\n\1', text)

    # Collapse any run of 3+ newlines that the promotion step may have created
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Standard cleanup: join single \n within a paragraph into spaces
    paragraphs = text.split('\n\n')
    for i, para in enumerate(paragraphs):
        paragraphs[i] = ' '.join(para.splitlines())

    # Join the paragraphs back together with two newlines between them
    return '\n\n'.join(paragraphs)


def get_hashtags(text):
    # Find all hashtags in the text
    return re.findall(r'#\w+', text)


def extract_title(text):
    # Find the index of the first newline character
    newline_index = text.find('\n')

    # If no newline is found, return the whole string
    if newline_index == -1:
        return text

    # Return the substring from the start up to (but not including) the newline
    return text[:newline_index]


def compile_unique_hashtags(text, all_hashtags):
    all_hashtags.update(get_hashtags(text))
    return all_hashtags


def compile_unique_hashtags1(*texts):
    # Use a set to store unique hashtags
    all_hashtags = set()

    # Iterate over each text provided
    for text in texts:
        all_hashtags.update(get_hashtags(text))

    # Convert the set back to a space-separated string
    return ' '.join(sorted(all_hashtags))  # Sorting is optional


def remove_hashtags(text):
    # This regex pattern matches any word that starts with '#' and removes it
    # It also strips whitespace from both ends of the string
    return re.sub(r'#\w+', '', text).strip()


def remove_story_break(text):
    """
    Removes lines consisting of only '---' or '===' (with optional leading/trailing spaces).
    """
    return re.sub(r'(?m)^\s*(?:---|=+)\s*$\n?', '', text)


def edit_title(text):
    text = re.sub(r'^Title:', '', text)
    text = re.sub(r'^Title', '', text)
    text = re.sub(r'^Report Title:', '', text)
    text = re.sub(r'^Report Title', '', text)
    text = re.sub(r'Introduction$', '', text)
    # Replace sequences of "=":
    # If the sequence has 1 or 2 equals, keep it; if more than 2, remove it entirely.
    text = re.sub(r"=+", lambda m: m.group(0) if len(m.group(0)) <= 2 else "", text)
    # Remove matching quotes at the start and end, if present.
    text = text.strip()
    text = text.strip('"“”')

    return text.strip()


def embed_plot_url(md_text, md_kv):
    """
    Replace Markdown tags in md_text with Markdown image references
    using URLs from md_kv.

    Args:
        md_text (str): Markdown text containing plot tags to replace
        md_kv (dict): Mapping of plot tags to their corresponding URLs

    Returns:
        str: Modified markdown text with embedded image references
    """
    result = md_text
    for plot_tag, url in md_kv.items():
        md_image = f"![{plot_tag}]({url})\n  "  # Simplified formatting
        result = result.replace(plot_tag, md_image)
    return result


