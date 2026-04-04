#!/usr/bin/env python3
"""
st — Interactive command menu and launcher

Design intent:
  - This file builds and runs shell commands; it contains NO business logic.
  - Every action ultimately calls one of the st-* CLI tools directly.
  - The user can bypass this UI at any time and run any st-* command by hand.
  - Menu structure: Generate → View → Edit → Analyze → Post (top-down workflow).

Adding a new command:
  1. Add a label entry to the relevant submenu dict below.
  2. Add the corresponding case to execute_menu().
  3. If the command mutates the .json container, add it to post_cmd_initialize_state.
"""
import argparse
import json
import os
import subprocess
import sys

from dotenv import load_dotenv
from ai_handler import get_ai_list, get_default_ai
from discourse import get_discourse_slugs_sites
from mmd_single_key import get_single_key, line_edit

slugs, sites = get_discourse_slugs_sites()
site_sel = slugs[0] if slugs else ""  # Currently selected Discourse site

# Commands that mutate the .json container — state is re-read after these run.
# st.py builds and fires the command; the st-* tool owns all the logic.
# Note: st-edit is intentionally excluded — view-only and edit operations do not
# require a container refresh, and refreshing would reset story_sel to 1.
POST_CMD_REFRESH = {
    "st-gen", "st-prep", "st-bang", "st-merge",
    "st-fact", "st-cross", "st-analyze",
    "st-fix", "st-rm",
}

menus = {
    "main": {
        "g": ("Generate", {
            "g": "Generate and prep a story from a prompt",
            "e": "Edit a prompt file",
            "s": "Spell check a prompt file",
            "b": "Parallel generate all AI stories (Bang!)",
            "B": "Parallel generate all AI and merge",
            "m": "Merge stories 1-5 into a master story"
        }),
        "v": ("View", {
            "v": "View story with browser",
            "s": "List stories",
            "l": "List stories and fact-checks",
            "a": "List all contents of .json file",
            "f": "List fact-checks",
            "F": "Edit a fact-check",
        }),
        "e": ("Edit", {
            "T": "Edit title",
            "m": "Edit markdown",
            "M": "Edit markdown with browser view",
            "v": "View story with browser",
            "s": "Edit spoken",
            "t": "Edit text",
            "f": "Edit fact-check",
            "x": "Fix a story using fact-check feedback",
            "g": "Merge all original stories (quality, no post-check)"
        }),
        "a": ("Analyze", {
            "f": "Fact-check current story, current AI",
            "F": "Fact-check all stories, current AI",
            "@": "Fact-check current story, all AI",
            "c": "Cross-product fact-check — all stories  all AI",
            "C": "Generate Cross-Product report",
            "s": "Cross-Stones benchmark leaderboard (cross_stones/)",
            "v": "View fact-check",
            "r": "Show reading metrics",
            "R": "Show reading metrics with legend",
        }),
        "p": ("Post", {
            "n": "Select site",
            "p": "Post story",
            "a": "Post story with mp3 audio",
            "f": "Post fact-check",
            "v": "Preview post",
            "d": "Save story as PDF  (st-print --save-pdf)",
            "D": "Print story to default printer  (st-print)",
        }),
        "u": ("Utility", {
            "p": "View all Cross-Product plots",
            "P": "Save all Cross-Product plots",
            "r": "Remove story (and fact-checks)",
            "R": "Remove fact-check",
            "v": "Speak story aloud with current voice",
            "V": "Render current voice to mp3 file",
        }),
        "x": ("Settings", {
            "a": "Open admin settings panel  (st-admin)",
            "s": "Show all current settings",
        }),
    }
}

# State global variables — initialized AFTER load_dotenv so DEFAULT_AI is honoured
ai_opt = get_ai_list()
file_json = None
file_prefix = None
story_sel = None
fact_sel = None
main_container = {}
cmd = ""

# Settings — resolved at startup, writable back to .env
_CROSSENV = os.path.expanduser("~/.crossenv")
load_dotenv(_CROSSENV)                                    # 1. global ~/.crossenv
load_dotenv(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".env"))  # 2. repo-local
load_dotenv(".env", override=True)                        # 3. CWD .env overrides both

# Pick the user-configured default AI now that .env is loaded
_default_ai = get_default_ai()
ai_select = ai_opt.index(_default_ai) if _default_ai in ai_opt else 0
ai = ai_opt[ai_select]



def refresh_main_container():
    global main_container
    with open(file_json, 'r') as file:
        main_container = json.load(file)


def initialize_state():
    """First-run setup — resets story_sel and fact_sel to 1 (or None)."""
    global main_container, story_sel, fact_sel
    refresh_main_container()
    story_sel = 1 if main_container.get('story') else None
    facts = main_container['story'][story_sel - 1].get('fact', []) if story_sel else []
    fact_sel = 1 if facts else None


def refresh_state():
    """
    Re-read the container after a mutating command, but preserve the current
    story_sel and fact_sel if they are still valid. Only clamp when the
    container has shrunk (e.g. after st-rm removed the selected story).
    """
    global main_container, story_sel, fact_sel
    refresh_main_container()
    stories = main_container.get('story', [])
    n_stories = len(stories)

    if n_stories == 0:
        story_sel = None
        fact_sel = None
        return

    # Clamp story_sel only if it's out of range or unset
    if story_sel is None or story_sel > n_stories:
        story_sel = n_stories  # point to the newest story (e.g. just generated)

    facts = stories[story_sel - 1].get('fact', [])
    n_facts = len(facts)
    if fact_sel is None or fact_sel > n_facts:
        fact_sel = n_facts if n_facts else None


def display_menu(menu, menu_name):
    """Displays the current menu when requested."""
    print(f"\n=== {menu_name} Menu ===")
    for key, value in menu.items():
        if isinstance(value, tuple):  # Submenu
            print(f"{key}: {value[0]}")
        else:  # Command
            label = value
            # Inject active site into Post menu items that target a specific site
            if menu_name.endswith("Post"):
                rotation = "[" + ", ".join(
                    f"*{s}*" if s == site_sel else s for s in slugs
                ) + "]"
                if key == "n":
                    label = f"Select site: {rotation}"
                elif key in ("p", "a", "f", "L"):
                    label = f"{value}  → {site_sel}"
            print(f"{key}: {label}")
    print("\nesc: Escape back to the previous menu")
    print("?: Display this menu")
    print("ASF: Next Ai, Story, Fact")


def get_prompt(menu_names):
    """Generate the dynamic command prompt including state variables and menu names."""
    menu_path = ">".join(menu_names)
    return f"st ai:{ai_opt[ai_select]} s:{story_sel} f:{fact_sel} {menu_path}> "


def execute_menu(menu_name, choice):
    """Execute the correct command based on the current menu."""
    global cmd

    match menu_name:
        case "Generate":
            match choice:
                case "g":
                    cmd = f"st-gen --prep --ai {ai} {file_prefix + '.prompt'}"
                case "e":
                    cmd = f"vi {file_prefix + '.prompt'}"
                case "s":
                    cmd = f"aspell check {file_prefix + '.prompt'}"
                case "b":
                    cmd = f"st-bang {file_json}"
                case "B":
                    cmd = f"st-bang --merge --ai {ai} {file_json}"
                case "m":
                    cmd = f"st-merge --ai {ai} --stories 1 2 3 4 5 -- {file_json}"

        case "Edit":
            match choice:
                case "T":
                    cmd = f"st-edit --title -s {story_sel} {file_json}"
                case "m":
                    cmd = f"st-edit --markdown -s {story_sel} {file_json}"
                case "M":
                    cmd = f"st-edit --view --markdown -s {story_sel} {file_json}"
                case "v":
                    cmd = f"st-edit --view-only --markdown -s {story_sel} {file_json}"
                case "s":
                    cmd = f"st-edit --spoken -s {story_sel} {file_json}"
                case "t":
                    cmd = f"st-edit --text -s {story_sel} {file_json}"
                case "f":
                    cmd = f"st-edit -s {story_sel} -f {fact_sel} {file_json}"
                case "x":
                    cmd = f"st-fix --ai {ai} -s {story_sel} -f {fact_sel} {file_json}"
                case "g":
                    cmd = f"st-merge --quality --no-post-check {file_json}"
                case _:
                    print("\nCommand not implemented yet.")

        case "View":
            match choice:
                case "v":
                    cmd = f"st-edit --view-only --markdown -s {story_sel} {file_json}"
                case "s":
                    cmd = f"st-ls --story {file_json}"
                case "l":
                    cmd = f"st-ls --story --fact {file_json}"
                case "a":
                    cmd = f"st-ls --all {file_json}"
                case "f":
                    cmd = f"st-ls --fact {file_json}"
                case "F":
                    cmd = f"st-edit -s {story_sel} -f {fact_sel} {file_json}"
                case _:
                    print("\nCommand not implemented yet.")

        case "Analyze":
            match choice:
                case "f":
                    cmd = f"st-fact --ai {ai} -s {story_sel} {file_json}"
                case "F":
                    cmd = f"st-fact --ai {ai} {file_json}"
                case "@":
                    cmd = f"st-fact --ai all -s {story_sel} {file_json}"
                case "c":
                    cmd = f"st-cross {file_json}"
                case "C":
                    cmd = f"st-analyze --ai {ai} {file_json}"
                case "s":
                    cmd = "st-stones --domain cross_stones/"
                case "v":
                    cmd = f"st-edit --view-only -s {story_sel} -f {fact_sel} {file_json}"
                case "r":
                    cmd = f"st-read {file_json}"
                case "R":
                    cmd = f"st-read --legend {file_json}"
                case _:
                    print("\nCommand not implemented yet.")

        case "Post":
            match choice:
                case "n":
                    post_rotate_next_social_media()
                case "p":
                    cmd = f"st-post --site {site_sel} -s {story_sel} {file_json}"
                case "a":
                    cmd = f"st-post --site {site_sel} -s {story_sel} {file_prefix + '.mp3'} {file_json}"
                case "f":
                    cmd = f"st-post --site {site_sel} -f {fact_sel} -s {story_sel} {file_json}"
                case "v":
                    cmd = f"st-edit --view-only --markdown -s {story_sel} {file_json}"
                case "d":
                    cmd = f"st-print --save-pdf -s {story_sel} {file_json}"
                case "D":
                    cmd = f"st-print -s {story_sel} {file_json}"
                case _:
                    print("\nCommand not implemented yet.")

        case "Utility":
            match choice:
                case "p":
                    cmd = f"st-plot --plot all --display {file_json}"
                case "P":
                    cmd = f"st-plot --plot all --file --path ./tmp {file_json}"
                case "r":
                    cmd = f"st-rm -s {story_sel} {file_json}"
                case "R":
                    cmd = f"st-rm -s {story_sel} -f {fact_sel} {file_json}"
                case "v":
                    # Render then play aloud — two sequential steps
                    mp3 = file_prefix + '.mp3'
                    speak_cmd = f"st-speak -s {story_sel} {file_json}".split()
                    play_cmd  = f"afplay {mp3}".split()
                    print(f"\n\nExecuting command: st-speak -s {story_sel} {file_json} && afplay {mp3}")
                    try:
                        result = subprocess.run(speak_cmd)
                        if result.returncode == 0:
                            print(f"  Audio: {os.path.abspath(mp3)}")
                            subprocess.run(play_cmd)
                    except KeyboardInterrupt:
                        print()  # clean line after ^C
                case "V":
                    mp3 = file_prefix + '.mp3'
                    speak_cmd = f"st-speak -s {story_sel} {file_json}".split()
                    print(f"\n\nExecuting command: st-speak -s {story_sel} {file_json}")
                    try:
                        result = subprocess.run(speak_cmd)
                        if result.returncode == 0:
                            print(f"  Audio: {os.path.abspath(mp3)}")
                    except KeyboardInterrupt:
                        print()  # clean line after ^C
                case _:
                    print("\nCommand not implemented yet.")

        case "Settings":
            match choice:
                case "a":
                    cmd = "st-admin"
                case "s":
                    cmd = "st-admin --show"
                case _:
                    print("\nCommand not implemented yet.")

        case _:
            print("\nUnknown menu. Command execution failed.")


def valid_file_extension(filename):
    if not (filename.endswith('.json') or filename.endswith('.prompt')):
        print("File must end with .json or .prompt")
        sys.exit(1)
    return filename


def main():
    global cmd
    global file_json
    global file_prefix
    global slugs
    global site_sel

    parser = argparse.ArgumentParser(
        prog='st',
        description='Use AI to create, fact-check and post reports online.')
    parser.add_argument('input_file', type=valid_file_extension,
                        help='Path to the .json or .prompt file', metavar='file.json | file.prompt')
    parser.add_argument('--site', type=str, choices=slugs, default=slugs[0],
                        help=f"Define Discourse site to use, default is {slugs[0]}")
    parser.add_argument('-a', '--ai', type=str, choices=ai_opt, default=get_default_ai(),
                        help=f'AI model to start with, default is {get_default_ai()}')
    parser.add_argument('-b', '--bang', action='store_true',
                        help='Submit prompt to each AI in parallel (bang!), default: no bang')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Minimal output, default: quiet on')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output, default: verbose off')

    args = parser.parse_args()
    site_sel = args.site
    file_prefix = args.input_file.rsplit('.', 1)[0]  # Split from the right, only once

    file_json = file_prefix + ".json"
    file_prompt = file_prefix + ".prompt"

    # User supplied a prompt, lets st-gen, and have st-gen run st-prep
    if not os.path.isfile(file_json) and os.path.isfile(file_prompt):
        if args.bang:
            cmd = f"st-bang {file_prompt}".split()
        else:
            cmd = f"st-gen --prep --ai {args.ai} {file_prompt}".split()
        subprocess.run(cmd)
        cmd = ""

    if not os.path.isfile(file_json):  # Something probably failed in the st-gen process
        print(f"Error: The file {file_json} does not exist.")
        sys.exit(1)

    initialize_state()

    """Handles the navigation of the two-level menu system."""
    current_menu = menus["main"]
    menu_stack = []  # Stack to track menu history
    menu_names = ["Main"]  # Track menu names for dynamic prompt
    show_menu = True  # Controls when to display the menu

    while True:
        if show_menu:
            display_menu(current_menu, ">".join(menu_names))  # Consistent formatting
            show_menu = False  # Only show menu when `?` is pressed

        prompt = get_prompt(menu_names)
        print(f"\n{prompt}{cmd}", end="", flush=True)  # Display dynamic prompt

        key = get_single_key()  # Preserve case sensitivity

        if key == "ESC":  # Escape key (ASCII escape character)
            if menu_stack and cmd == "":
                current_menu = menu_stack.pop()  # No cmd, go back to previous menu
                menu_names.pop()  # Update menu name
                print()  # Ensure clean prompt after going back
            elif menu_stack:  # Hit escape with cmd, abort cmd, stay in menu
                cmd = ""
            else:
                print("\nExiting program.")
                sys.exit(0)
        elif key in ["DELETE", "LEFT"]:  # Trigger editing mode
            cmd = line_edit(prompt, cmd)
        elif key == "?":
            show_menu = True  # Show menu on `?`
        elif key in ["A", "S", "F"]:
            match key:
                case "A": next_ai()
                case "S": next_story()
                case "F": next_fact_check()
        elif key in current_menu:
            if isinstance(current_menu[key], tuple):
                menu_stack.append(current_menu)  # Save current menu state
                menu_names.append(current_menu[key][0])  # Update menu name
                current_menu = current_menu[key][1]  # Navigate to submenu
                show_menu = True  # Show new menu
            else:
                execute_menu(menu_names[-1], key)  # Pass the current menu and command
        elif key == "RETURN":
            if cmd != "":
                print(f"\n\nExecuting command: {cmd}")
                cmd_split = cmd.split()
                cmd = ""
                try:
                    subprocess.run(cmd_split)
                except KeyboardInterrupt:
                    print()   # blank line after ^C
                    pass      # return cleanly to the st menu

                # Re-read container state after any command that mutates it
                if cmd_split[0] in POST_CMD_REFRESH:
                    refresh_state()
        else:
            print(f"\nInvalid choice {key}. Please try again.")


def next_ai():
    global ai_select
    global ai
    ai_select = (ai_select + 1) % len(ai_opt)
    ai = ai_opt[ai_select]



def next_story():
    global story_sel
    global fact_sel
    global main_container
    refresh_main_container()  # can be updated by gen, prep, rm...
    stories = main_container.get('story')
    if story_sel is not None and stories:
        story_sel = (story_sel % len(stories)) + 1
    story = stories[story_sel - 1]
    facts = story.get('fact', [])
    if facts:
        fact_sel = 1
    else:
        fact_sel = None


def next_fact_check():
    global fact_sel
    global story_sel
    global main_container
    if isinstance(story_sel, int) and isinstance(fact_sel, int):
        fact = main_container['story'][story_sel - 1].get('fact', [])
        fact_sel = (fact_sel % len(fact)) + 1


def post_rotate_next_social_media():
    global site_sel
    site_sel = slugs[(slugs.index(site_sel) + 1) % len(slugs)]
    rotation = "[" + ", ".join(
        f"*{s}*" if s == site_sel else s for s in slugs
    ) + "]"
    print(f"\n  Site → {site_sel}   {rotation}")


if __name__ == "__main__":
    main()
