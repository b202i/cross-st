#!/usr/bin/env python3
"""
## st-find — Search for keywords in story containers and prompts

Searches for keywords (with wildcards) in titles, prompts, and story content
stored in .json containers and .prompt files.

Simple searches:
```
st-find keyword                     # search all fields in current dir  
st-find "bicycle*" -t               # search titles for bicycle* (quotes for wildcards)
st-find "*bike*" -t -r              # search titles recursively
st-find "pizza*" template -p        # search prompts in template dir
st-find "AI*" -s                    # search story text
st-find "report*" file.json         # search specific file
st-find "*guide*" ../other -r -v    # recursive verbose search
```

Boolean Search (combine keywords - no quotes needed for AND/OR/NOT):
```
st-find +pizza +dough -t            # both pizza AND dough required (no quotes!)
st-find +bike ^electric -s          # bike required, electric excluded
st-find +report "AI*" OpenAI -s     # report required, AI* or OpenAI optional
st-find bike bicycle -t             # either bike OR bicycle
st-find +camping ^RV ^electric -t   # camping, but not RV or electric
```

Quoted patterns (when needed):
```
st-find "deep learning" -t          # exact phrase
st-find "bike*" -t                  # wildcards (* ?) must be quoted
st-find "+pizza +dough" -t          # can quote boolean operators too
```

Boolean Operators:
  +keyword  - REQUIRED (must be present, AND logic)
  ^keyword  - EXCLUDED (must not be present, NOT logic)
  keyword   - OPTIONAL (at least one must match, OR logic)

Wildcards:
  *  matches any sequence of characters (e.g., "bike*" matches "bicycle", "bike shop")
  ?  matches any single character (e.g., "AI?" matches "AIs", "AIR")
  
  Note: Wildcards (* ?) must be quoted to prevent shell expansion:
    st-find "bike*" -t          # correct
    st-find bike* -t            # incorrect - shell expands * first

Search is case-insensitive by default.

Path Detection:
  The last argument is treated as a file/directory path if it:
  - Ends in .json or .prompt
  - Contains a / (path separator)
  - Is an existing file or directory
  Otherwise all arguments are treated as search keywords.

Options: -t/--title  -p/--prompt  -s/--story  -a/--all  -r/--recursive  -v/--verbose
"""

import argparse
import json
import os
import re
import sys
from mmd_startup import require_config
from pathlib import Path
from fnmatch import fnmatch
from tabulate import tabulate


def parse_boolean_pattern(pattern):
    """
    Parse boolean search pattern into required/optional/excluded keywords.
    
    Examples:
        "+pizza +dough" → both required
        "+pizza ^frozen" → pizza required, frozen excluded
        "bike bicycle" → either word matches (OR)
        "+report *AI*" → report required, wildcard AI* optional
    
    Returns:
        (required_patterns, optional_patterns, excluded_patterns)
        Each is a list of compiled regex patterns.
    """
    required = []
    optional = []
    excluded = []
    
    # Split by whitespace and parse each term
    terms = pattern.split()
    
    for term in terms:
        if term.startswith('+'):
            # Required term (AND)
            keyword = term[1:]
            if keyword:
                required.append(wildcard_to_regex(keyword))
        elif term.startswith('^'):
            # Excluded term (NOT)
            keyword = term[1:]
            if keyword:
                excluded.append(wildcard_to_regex(keyword))
        else:
            # Optional term (OR)
            optional.append(wildcard_to_regex(term))
    
    # If only required/excluded terms, add a match-all optional pattern
    if not optional and (required or excluded):
        optional.append(re.compile('.*', re.IGNORECASE))
    
    return required, optional, excluded


def wildcard_to_regex(pattern):
    """Convert shell-style wildcard pattern to regex, case-insensitive."""
    # Escape special regex characters except * and ?
    pattern = re.escape(pattern)
    # Convert \* to .* and \? to .
    pattern = pattern.replace(r'\*', '.*').replace(r'\?', '.')
    return re.compile(pattern, re.IGNORECASE)


def text_matches_boolean(text, required_patterns, optional_patterns, excluded_patterns):
    """
    Check if text matches the boolean search criteria.
    
    Returns:
        (matches, first_match_pos) - True if matches, and position of first keyword found
    """
    # Check excluded patterns first (fastest rejection)
    for pattern in excluded_patterns:
        if pattern.search(text):
            return False, None
    
    # Check required patterns (all must match)
    first_pos = None
    for pattern in required_patterns:
        match = pattern.search(text)
        if not match:
            return False, None
        if first_pos is None:
            first_pos = match.start()
    
    # Check optional patterns (at least one must match)
    if optional_patterns:
        for pattern in optional_patterns:
            match = pattern.search(text)
            if match:
                if first_pos is None:
                    first_pos = match.start()
                return True, first_pos
        return False, None
    
    return True, first_pos if first_pos is not None else 0


def get_context(text, match_start, match_end, context_chars=40):
    """Extract context around a match in text."""
    start = max(0, match_start - context_chars)
    end = min(len(text), match_end + context_chars)
    
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    
    context = text[start:end].replace('\n', ' ').strip()
    return f"{prefix}{context}{suffix}"


def search_prompt_file(filepath, required_patterns, optional_patterns, excluded_patterns):
    """Search a .prompt file for pattern matches."""
    results = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            matches, first_pos = text_matches_boolean(content, required_patterns, optional_patterns, excluded_patterns)
            if matches:
                # Find the first actual keyword match for context
                context_start = first_pos
                context_end = min(first_pos + 20, len(content))
                context = get_context(content, context_start, context_end)
                results.append({
                    'file': str(filepath),
                    'type': 'prompt',
                    'story_num': '',
                    'field': 'prompt',
                    'context': context
                })
    except Exception as e:
        pass  # Silently skip files that can't be read
    return results


def search_json_file(filepath, required_patterns, optional_patterns, excluded_patterns, search_title=False, search_story=False):
    """Search a .json container file for pattern matches."""
    results = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            container = json.load(f)
        
        # Search in stories
        stories = container.get('story', [])
        for i, story in enumerate(stories, start=1):
            # Search title
            if search_title:
                title = story.get('title', '')
                if title:
                    matches, first_pos = text_matches_boolean(title, required_patterns, optional_patterns, excluded_patterns)
                    if matches:
                        context = get_context(title, first_pos, min(first_pos + 20, len(title)), context_chars=60)
                        results.append({
                            'file': str(filepath),
                            'type': 'json',
                            'story_num': str(i),
                            'field': 'title',
                            'context': context
                        })
            
            # Search story text (limit to first match per story to avoid spam)
            if search_story:
                for field in ['text', 'markdown', 'spoken']:
                    text = story.get(field, '')
                    if text:
                        matches, first_pos = text_matches_boolean(text, required_patterns, optional_patterns, excluded_patterns)
                        if matches:
                            context = get_context(text, first_pos, min(first_pos + 20, len(text)))
                            results.append({
                                'file': str(filepath),
                                'type': 'json',
                                'story_num': str(i),
                                'field': field,
                                'context': context
                            })
                            break  # Only first matching field per story
        
        # Note: We don't search data/prompt here because .prompt files 
        # are already searched separately and data/prompt is just a copy
    
    except Exception as e:
        pass  # Silently skip files that can't be read
    
    return results


def find_files(start_path, recursive=False):
    """Find all .json and .prompt files in the given path."""
    start_path = Path(start_path)
    
    if start_path.is_file():
        return [start_path]
    
    if not start_path.is_dir():
        return []
    
    files = []
    if recursive:
        for ext in ['*.json', '*.prompt']:
            files.extend(start_path.rglob(ext))
    else:
        for ext in ['*.json', '*.prompt']:
            files.extend(start_path.glob(ext))
    
    return sorted(files)


def main():
    require_config()
    parser = argparse.ArgumentParser(
        prog='st-find',
        description='Search for keywords in story containers and prompts')
    
    parser.add_argument('pattern', type=str, nargs='+',
                        help='Search pattern - multiple keywords supported (use quotes for wildcards)')
    parser.add_argument('-t', '--title', action='store_true',
                        help='Search in story titles')
    parser.add_argument('-p', '--prompt', action='store_true',
                        help='Search in prompts')
    parser.add_argument('-s', '--story', action='store_true',
                        help='Search in story text/markdown/spoken')
    parser.add_argument('-a', '--all', action='store_true', default=False,
                        help='Search in all fields (default if no flags specified)')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='Search recursively in subdirectories')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    
    args = parser.parse_args()
    
    # Smart detection: if last arg looks like a file/directory, treat it as path
    # Otherwise, all args are part of the pattern
    pattern_parts = args.pattern
    path = '.'
    
    if len(pattern_parts) > 1:
        last_arg = pattern_parts[-1]
        # Check if last arg looks like a file or directory
        if (last_arg.endswith('.json') or 
            last_arg.endswith('.prompt') or 
            os.path.isdir(last_arg) or
            os.path.isfile(last_arg) or
            '/' in last_arg):
            # Last arg is likely a path
            path = pattern_parts[-1]
            pattern_parts = pattern_parts[:-1]
    
    # Reconstruct pattern from parts
    pattern = ' '.join(pattern_parts)
    
    # If no search flags specified, search all
    if not (args.title or args.prompt or args.story):
        args.all = True
    
    if args.all:
        args.title = True
        args.prompt = True
        args.story = True
    
    # Parse boolean search pattern
    required_patterns, optional_patterns, excluded_patterns = parse_boolean_pattern(pattern)

    if args.verbose:
        print(f"Searching for pattern: {pattern}")
        if required_patterns:
            print(f"  Required (+): {len(required_patterns)} pattern(s)")
        if optional_patterns:
            print(f"  Optional: {len(optional_patterns)} pattern(s)")
        if excluded_patterns:
            print(f"  Excluded (^): {len(excluded_patterns)} pattern(s)")
        print(f"Search in: title={args.title}, prompt={args.prompt}, story={args.story}")
        print(f"Path: {path}, recursive: {args.recursive}")
        print()
    
    # Find all files to search
    files = find_files(path, args.recursive)

    if args.verbose:
        print(f"Found {len(files)} file(s) to search")
        print()
    
    # Search all files
    all_results = []
    for filepath in files:
        if filepath.suffix == '.prompt':
            if args.prompt:
                results = search_prompt_file(filepath, required_patterns, optional_patterns, excluded_patterns)
                all_results.extend(results)
        elif filepath.suffix == '.json':
            results = search_json_file(filepath, required_patterns, optional_patterns, excluded_patterns,
                                     search_title=args.title,
                                     search_story=args.story)
            all_results.extend(results)
    
    # Display results
    if not all_results:
        print(f"No matches found for pattern: {pattern}")
        return
    
    # Format results as table
    table_data = []
    for result in all_results:
        table_data.append([
            result['file'],
            result['story_num'],
            result['field'],
            result['context'][:80]  # Limit context width
        ])
    
    print(tabulate(table_data, 
                   headers=['File', 'Story', 'Field', 'Context'],
                   tablefmt='simple'))
    
    print(f"\nFound {len(all_results)} match(es)")


if __name__ == '__main__':
    main()
