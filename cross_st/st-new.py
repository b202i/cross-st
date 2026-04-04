#!/usr/bin/env python3
"""
st-new — Start a new report from a prompt template

Creates a fresh prompt file from a template and opens your editor so you can
fill in the topic. The starting point for every new research report.

Run before: st-gen   (generate a report from one AI provider)
            st-bang  (generate from all AI providers in parallel)

```
st-new                                  # pick a template interactively
st-new --template custom subject        # use a named template
st-new --no-bang                        # edit only, skip st-bang
```

Options: --template  --no-bang  --no-spell  -v  -q
"""
import argparse
import os
import shutil
import subprocess
import sys
from mmd_startup import load_cross_env, require_config

from mmd_util import seed_user_templates, _USER_TEMPLATES_DIR, _BUNDLED_TEMPLATES_DIR

"""
Ease the report creation process.
1. Copy a template prompt into a name chosen by the user.
2. Start the text editor on the new prompt.
3. Run a spell check when editor quits (optional, no-spell).
4. Start the 'st' app when editing is complete.
"""

def _resolve_template_dir() -> str:
    """
    Resolve the template directory using a priority chain:
      1. ./template/  in CWD           — developer working-directory override
      2. ~/.cross_templates/            — standard user/pip-install location (A1)
      3. <script-dir>/template/         — repo-relative fallback
    Returns the first directory that exists and contains at least one .prompt file.

    On first run (when ~/.cross_templates/ is absent or empty) the bundled
    templates are silently seeded there so pip-installed users always have
    defaults without any manual setup step.
    """
    _script_dir = os.path.dirname(os.path.realpath(__file__))
    bundled = os.path.join(_script_dir, "template")

    # Auto-seed ~/.cross_templates/ from bundled templates if it has no prompts yet.
    user_dir = str(_USER_TEMPLATES_DIR)
    if not (os.path.isdir(user_dir) and any(f.endswith(".prompt") for f in os.listdir(user_dir))):
        seed_user_templates(src_dir=bundled, overwrite=False, quiet=True)

    candidates = [
        os.path.join(os.getcwd(), "template"),
        user_dir,
        bundled,
    ]
    for path in candidates:
        if os.path.isdir(path) and any(f.endswith(".prompt") for f in os.listdir(path)):
            return path
    # fallback: return first existing dir, else ~/.cross_templates
    for path in candidates:
        if os.path.isdir(path):
            return path
    return user_dir


template_dir = _resolve_template_dir()


def get_template_list():
    """
    Returns a list of template filenames (without extensions) from the template folder.
    """
    try:
        # Get all files in the template directory
        files = os.listdir(template_dir)
        # Filter for prompt template file extension
        valid_extensions = '.prompt'
        templates = [
            os.path.splitext(f)[0]  # Get filename without extension
            for f in files
            if f.endswith(valid_extensions)
        ]
        return templates if templates else ['default']  # Return default if no templates found
    except FileNotFoundError:
        # Return a default template if directory doesn't exist
        return ['default']


def main():
    require_config()
    load_cross_env()

    parser = argparse.ArgumentParser(
        prog='st-new',
        description='Start a new report prompt from template')
    parser.add_argument('prompt', type=str,
                        help='Name for the prompt file, with or without .prompt')
    parser.add_argument('-t', '--template', type=str, choices=get_template_list(),
                        help='Template to use')
    parser.add_argument('-b', '--bang', action='store_true', default=False,
                        help='Start "st-bang" app after editing, render with all AI. '
                             'Start "st" if you also use "--st".')
    parser.add_argument('-s', '--st', action='store_true', default=False,
                        help='Start the "st" app after editing, render with default AI')
    parser.add_argument('-n', '--no-spell', action='store_true',
                        help='Disable spell check')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output, default is verbose')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Enable minimal output')
    args = parser.parse_args()
    if args.verbose:
        print(f"st-new args: {args}")

    # Give user flexibility to enter name or name.prompt
    file_prefix = args.prompt.rsplit('.', 1)[0]  # Split from the right, only once
    file_prompt = file_prefix + ".prompt"
    file_json = file_prefix + ".json"

    # Handle template copying
    if args.prompt:
        template_name = args.template if args.template else 'default'
        source_path = os.path.join(template_dir, f"{template_name}.prompt")
        dest_path = os.path.join(os.getcwd(), file_prompt)

        try:
            # Check if source template exists
            print(f"source_path: {source_path}")
            if not os.path.exists(source_path):
                print(f"Error: Template '{template_name}.prompt' not found in template directory")
                return

            # Copy the template to current directory with new name
            shutil.copy2(source_path, dest_path)

            if args.verbose and not args.quiet:
                print(f"Copied {template_name}.prompt to {args.prompt}.prompt")
            elif not args.quiet:
                print(f"Created {args.prompt}.prompt")

        except Exception as e:
            print(f"Error copying template: {str(e)}")
            sys.exit(1)

        editor = os.getenv("EDITOR", "vi")
        cmd = f"{editor} {file_prompt}"
        subprocess.run(cmd.split())

        if not args.no_spell:
            cmd = f"aspell check {file_prompt}"
            subprocess.run(cmd.split())

        if args.bang:
            cmd = f"st-bang {file_prompt}"
            subprocess.run(cmd.split())
            if args.st:
                cmd = f"st {file_json}"
                subprocess.run(cmd.split())
            sys.exit(0)

        if args.st:
            cmd = f"st {file_prompt}"
            # subprocess.Popen(cmd.split())  # Run and never come back
            # TODO consider run and never come back, to release all resources
            subprocess.run(cmd.split())
            sys.exit(0)


if __name__ == "__main__":
    main()