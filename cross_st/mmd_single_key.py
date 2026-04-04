#!/usr/bin/env python3
import sys
import tty
import termios
import fcntl
import os
import logging
import subprocess

# Configure logging (CRITICAL default, change to DEBUG/INFO for testing)
logging.basicConfig(level=logging.CRITICAL, format='%(message)s')
logger = logging.getLogger(__name__)


def get_single_key():
    """Reads a single keypress without requiring Enter, handling escape sequences and delete properly."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)

    try:
        tty.setraw(fd)  # Set terminal to raw mode
        key = sys.stdin.read(1)  # Blocking read for first character
        logger.debug(f"\nFirst char: {repr(key)} (ord: {ord(key) if key else 'None'})")

        if key == "\x1b":  # Escape key or start of an escape sequence
            logger.debug("\nDetected escape sequence start (\x1b)")
            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
            next_key = ""
            try:
                next_key = sys.stdin.read(1)
            except BlockingIOError:
                pass  # No more input available
            logger.debug(f"\nNext char (peek): {repr(next_key)} (ord: {ord(next_key) if next_key else 'None'})")

            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)

            if not next_key:
                logger.debug("\nNo next char, returning ESC")
                return "ESC"

            if next_key == "[":  # ANSI escape sequence
                logger.debug("\nDetected ANSI sequence (\x1b[)")
                final_key = sys.stdin.read(1)
                logger.debug(f"\nFinal char: {repr(final_key)} (ord: {ord(final_key) if final_key else 'None'})")

                if final_key == "":
                    logger.debug("\nNo final char, returning ESC")
                    return "ESC"

                key_mapping = {
                    "D": "LEFT", "C": "RIGHT", "A": "UP", "B": "DOWN",
                    "H": "HOME", "F": "END", "5": "PAGE_UP", "6": "PAGE_DOWN"
                }

                if final_key == "3":
                    tilde_key = sys.stdin.read(1)
                    logger.debug(f"\nTilde char after '3': {repr(tilde_key)} "
                                 f"(ord: {ord(tilde_key) if tilde_key else 'None'})")
                    if tilde_key == "~":
                        logger.debug("\nFull sequence \x1b[3~ matched, returning DELETE")
                        return "DELETE"
                    else:
                        logger.debug(f"\nIncomplete sequence, returning RAW: \x1b[3{tilde_key}]")
                        return f"RAW: \x1b[3{tilde_key}]"
                elif final_key in key_mapping:
                    if final_key in ("5", "6"):
                        sys.stdin.read(1)
                    logger.debug(f"\nMatched {final_key} to {key_mapping[final_key]}")
                    return key_mapping[final_key]
                else:
                    logger.debug(f"\nUnrecognized sequence, returning RAW: \x1b[{final_key}]")
                    return f"RAW: \x1b[{final_key}]"

            logger.debug("\nSingle \x1b detected, returning ESC")
            return "ESC"

        if key == "\x7f":
            logger.debug("\nDelete key (\x7f) detected, returning DELETE")
            return "DELETE"
        if key == "\r":  # Handle Return key
            logger.debug("\nReturn key detected, returning RETURN")
            return "RETURN"

        logger.debug(f"\nRegular key, returning {repr(key)}")
        return key

    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def display_line(prompt, cmd, cursor_pos):
    """Display the command line with prompt and cursor at cursor_pos in reverse video, hiding default cursor."""
    # Move cursor to start of line, clear it, and hide default cursor
    sys.stdout.write("\r\x1b[K\x1b[?25l")
    # Build display string with prompt and cursor in reverse video
    # display = cmd[:cursor_pos] + f"\x1b[7m{cmd[cursor_pos] if cursor_pos < len(cmd) else ' '}\x1b[0m" + cmd[cursor_pos + 1:]
    # Check if the cursor is within the command string
    if cursor_pos < len(cmd):
        highlighted_char = f"\x1b[7m{cmd[cursor_pos]}\x1b[0m"  # Highlight the character at the cursor position
    else:
        highlighted_char = f"\x1b[7m \x1b[0m"  # If at the end, highlight a space

    # Build the display string with the highlighted cursor position
    display = cmd[:cursor_pos] + highlighted_char + cmd[cursor_pos + 1:]

    sys.stdout.write(f"{prompt}{display}")
    sys.stdout.flush()


def line_edit(prompt, cmd):
    """Edit a single-line command string, returning the edited or original command."""
    original_cmd = cmd
    cursor_pos = len(cmd)  # Start at end
    debug = False  # Debug disabled per CRITICAL level

    # Hide cursor at start
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    try:
        while True:
            display_line(prompt, cmd, cursor_pos)

            key = get_single_key()

            if key == "ESC":  # Exit, discard changes
                logger.debug("\nExiting edit mode, returning original command")
                return original_cmd
            elif key == "RETURN":  # Exit, keep changes
                logger.debug("\nExiting edit mode, returning edited command")
                return cmd
            elif key == "DELETE" and cursor_pos > 0:  # Remove char left of cursor
                cmd = cmd[:cursor_pos - 1] + cmd[cursor_pos:]
                cursor_pos -= 1
            elif key == "LEFT" and cursor_pos > 0:  # Move cursor left
                cursor_pos -= 1
            elif key == "RIGHT" and cursor_pos < len(cmd):  # Move cursor right
                cursor_pos += 1
            elif key == "HOME":  # Move to start
                cursor_pos = 0
            elif key == "END":  # Move to end
                cursor_pos = len(cmd)
            elif len(key) == 1 and key.isprintable() and key != "\r":  # Insert printable char
                cmd = cmd[:cursor_pos] + key + cmd[cursor_pos:]
                cursor_pos += 1

            if debug and key != "ESC" and key != "RETURN":
                if key in ["LEFT", "RIGHT", "DELETE", "HOME", "END"]:
                    print(f"\nDetected: {key}")
                elif key.isprintable():
                    print(f"\nPressed: {key}")

    finally:
        # Show cursor and clean up on exit
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def main():
    prompt = f"Main (ESC to exit)> "
    cmd = "st-ls test.json"  # Fallback

    while True:
        print(f"\n{prompt}{cmd}", end="", flush=True)
        key = get_single_key()

        if key in ["DELETE", "LEFT"]:  # Trigger editing mode
            edited_cmd = line_edit(prompt, cmd)
            if edited_cmd:
                cmd = edited_cmd
                print(f"\nEdited command: {cmd}")
        elif key == "RETURN":  # Execute command
            print(f"\nExecuting: {cmd}")
            subprocess.run(cmd.split())
        elif key == "ESC":  # Exit menu
            if cmd != "":  # If the user hits esc while editing, abort edit
                cmd = ""
            else:
                print("\nExiting program.")
                break
        else:
            print(f"\nInvalid choice: {key}")


if __name__ == "__main__":
    main()
