import re

from mmd_process_report import remove_markdown
"""
Text Cleaner for TTS

This script provides functions to clean and prepare text for text-to-speach (TTS) systems.
It handles:
- Resolving ambiguous abbreviations based on context:
  - 'St.' is resolved to 'Saint' if followed by a capitalized word, otherwise 'Street'.
  - Other abbreviations are replaced using predefined mappings.
- Removing Markdown formatting to ensure the text is plain.
- Preserving or restoring periods at the end of sentences to maintain proper speech pauses.
Time expressions are handled by replacing 'a.m.' with 'AM' and 'p.m.' with 'PM', and removing the space between the number and the time marker (e.g., '10 p.m.' becomes '10PM').
The core function processes text in the following steps:
1. Split the text into paragraphs and lines to handle context correctly.
2. Resolve ambiguous abbreviations like 'St.' based on the following word.
3. Apply general replacements for standard abbreviations.
4. Ensure that sentence periods are preserved or restored after replacements.

Functions:
- clean_tts_text(text, verbose=True): The main text cleaning function.
- for_speaking(text, verbose=True): Prepares text for TTS by removing Markdown and adding pauses to headings.
- remove_markdown(text): Removes various Markdown elements from the text.

Usage:
Import this module and use the functions directly.
Example:
from text_cleaner import clean_tts_text
cleaned_text = clean_tts_text("Dr. Smith met with Mr. Johnson at 8 a.m.")
print(cleaned_text)
"""
titles = {
    'Dr.': 'Doctor',
    'Mr.': 'Mister',
    'Mrs.': 'Misses',
    'Ms.': 'Miss',
    'Prof.': 'Professor',
    'Sr.': 'Senior',
    'Jr.': 'Junior',
    'Rev.': 'Reverend'
}
time_units = {
    'a.m.': 'AM',
    'p.m.': 'PM',
    'min.': 'minute',
    'sec.': 'second',
    'hrs.': 'hours',
    'lb.': 'pounds',
    'oz.': 'ounces',
    'kg.': 'kilograms',
    'km.': 'kilometers',
    'cm.': 'centimeters',
    'mm.': 'millimeters',
}
places = {
    'U.S.': 'United States',
    'U.K.': 'United Kingdom',
    'E.U.': 'European Union',
    'Ave.': 'Avenue',
    'St.': 'Street'
}
misc = {
    'etc.': 'et cetera',
    'i.e.': 'that is',
    'e.g.': 'for example',
    'vs.': 'versus',
    'No.': 'Number',
    'Co.': 'Company',
    'Corp.': 'Corporation',
    'Inc.': 'Incorporated',
    'Ltd.': 'Limited',
}
ambiguity_patterns = [
    # Format: (pattern, replacement, debug_message)

    # St. → Saint (if followed by a capitalized word)
    (r'\bSt\.\s+([A-Z][a-z]+)', r'Saint \1', "Assuming 'Saint'"),

    # St. → Street (if NOT followed by a capitalized word)
    (r'\bSt\.\b(?!\s+[A-Z])', 'Street', "Assuming 'Street'"),

    # Co. → Company (if followed by Inc., Ltd., or Corp.)
    (r'\bCo\.\s+(Inc\.|Ltd\.|Corp\.)', r'Company \1', "Assuming 'Company'"),

    # Co. → County (if followed by a capitalized location name)
    (r'\bCo\.\s+([A-Z][a-z]+)', r'County \1', "Assuming 'County'"),

    # Ave. → Avenue (if preceded by a number)
    (r'(\d+)(?:st|nd|rd|th)?\s+Ave\.', r'\1 Avenue', "Assuming 'Avenue'"),

    # Ave. → Average (if followed by a sports term)
    (r'(?i)\b(Ave\.)\s+(batting|hitting|score|record)', r'Average \2', "Assuming 'Average'"),

    # Dr. → Doctor (if followed by a capitalized name)
    (r'\bDr\.\s+([A-Z][a-z]+)', r'Doctor \1', "Assuming 'Doctor'"),

    # Dr. → Drive (if not followed by a capitalized word)
    (r'\bDr\.\b(?!\s+[A-Z])', 'Drive', "Assuming 'Drive'")
]


def clean_tts_text(text, verbose=True):
    """Cleans text for TTS by resolving abbreviations and ensuring natural flow."""
    if verbose:
        print("\n 🚀 Original Text:\n", text)

    # Split into paragraphs to preserve Markdown structure
    paragraphs = text.split("\n\n")
    cleaned_paragraphs = []

    # Define replacement categories
    replacements = {**titles, **time_units, **places, **misc}

    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        cleaned_lines = []

        for line in lines:
            if verbose:
                print(f"\n🔹 Original Line: {repr(line)}")

            original_line = line  # Store the original line before any modifications

            # First, handle ambiguous cases like 'St.' based on context
            line = resolve_ambiguous_abbreviations(line, verbose)

            # Trim extra spaces within the line
            line = re.sub(r'\s+', ' ', line).strip()

            # Apply general replacements for abbreviations
            line = apply_general_replacements(line, replacements, verbose)

            # Ensure the line ends with a period if the original line did
            original_ends_with_period = original_line.strip().endswith(".")
            line = restore_period(line, original_ends_with_period, verbose)

            if verbose:
                print(f" ✅ Modified Line: {repr(line)}")
            cleaned_lines.append(line)

        cleaned_paragraphs.append("\n".join(cleaned_lines))

    final_text = "\n\n".join(cleaned_paragraphs)
    if verbose:
        print("\n ✅ Processed Text:\n", final_text)
    return final_text


def resolve_ambiguous_abbreviations(line, verbose):
    """Resolves context-dependent abbreviations, e.g., 'St.' as 'Saint' or 'Street'."""
    original_line = line
    # ambiguity_patterns = [
    #     (r'\bSt\.\s+([A-Z][a-z]+)', r'Saint \1', "Assuming 'Saint' for place name"),
    #     (r'\bSt\.\b(?!\s+[A-Z])', 'Street', "Assuming 'Street' for address"),
    #     Add other patterns as needed
    # ]
    for pattern, replacement, debug_message in ambiguity_patterns:
        if re.findall(pattern, line):
            if verbose:
                print(f"🔄 {debug_message}: {repr(line)}")
            line = re.sub(pattern, replacement, line)
    return line


def apply_general_replacements(line, replacements, verbose):
    """Applies standard replacements for abbreviations like 'Dr.' to 'Doctor'."""
    for key, value in replacements.items():
        if re.findall(rf'{re.escape(key)}(?=[\s,.)!?\-]|$)', line):
            if verbose:
                print(f"🔄 Replacing '{key}' → '{value}'")
            line = re.sub(rf'{re.escape(key)}(?=[\s,.)!?\-]|$)', value, line)
    return line


def restore_period(line, original_ends_with_period, verbose):
    """Restores period if the original line ended with one and it's lost, ensuring sentence-ending periods."""
    if original_ends_with_period and not line.endswith("."):
        if verbose:
            print("⚠️ Line lost its period. Restoring...")
        line = line.rstrip() + "."  # Ensure no trailing spaces and add period
    return line


def for_speaking(text, verbose=True):
    """
    Among the different formats for text is to use it for Text To Speech(TTS).
    The path to this point is long and detailed. The text was generated by
    one or more AI agents in Markdown format with a desired to present the article
    as spoken language in an mp3 audio container.

    The English language is complex, with a large number of abbreviations whose meaning
    changes depending on context, combined with a large number of rules involving punctuation.
    For example "They walked down St. Patrick St. looking for food etc." Should read
    "They walked down Saint Patrick Street looking for food et cetera." The context of
    "St. changes twice within 3 words with the challenge of substituting "etc." at the end of
    a sentence with a '.'.

    The TTS has trouble with headings. After reading a heading, there should be a short pause
    before continuing. This is accomplished by adding a '.' to the end of a heading line.

    :param text:
    :param verbose:
    :return: text:
    """

    # Replace --- with ''
    text = re.sub(r'---', '', text)
    # Replace = with ''
    text = re.sub(r'=', '', text)

    text = remove_markdown(text)

    text = clean_tts_text(text, verbose)
    # Put period at end of headings, to create a short pause
    # Regular expression pattern to match headings
    pattern = r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\n'
    # ^ → Start of a line.
    # ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*) → Captures title case words (potential headings).
    # •	\n → Ensures the line ends with a newline (no period yet).
    # re.sub(r'\1.\n', text, flags=re.MULTILINE) → Replaces
    # the match with the same text (\1) but adds a period (.) before the newline.
    text = re.sub(pattern, r'\1.  \n', text, flags=re.MULTILINE)

    return text