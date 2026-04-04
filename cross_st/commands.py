"""
commands.py — Entry-point dispatch for pyproject.toml [project.scripts].
pip generates a thin wrapper that imports and calls each function here;
runpy executes the st-*.py file directly so hyphens in filenames are never
treated as Python identifiers.
"""
import os
import runpy
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Ensure the cross_st/ directory is on sys.path so that st-*.py scripts can
# use bare module imports (e.g. `from mmd_startup import require_config`).
# When scripts are run directly as files, Python adds their directory to
# sys.path[0] automatically — runpy.run_path() does not, so we do it here.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _run(name: str) -> None:
    runpy.run_path(os.path.join(_HERE, f"{name}.py"), run_name="__main__")


def st():           _run("st")
def st_admin():     _run("st-admin")
def st_analyze():   _run("st-analyze")
def st_bang():      _run("st-bang")
def st_cat():       _run("st-cat")
def st_cross():     _run("st-cross")
def st_domain():    _run("st-domain")
def st_edit():      _run("st-edit")
def st_fact():      _run("st-fact")
def st_fetch():     _run("st-fetch")
def st_find():      _run("st-find")
def st_fix():       _run("st-fix")
def st_gen():       _run("st-gen")
def st_heatmap():   _run("st-heatmap")
def st_ls():        _run("st-ls")
def st_man():       _run("st-man")
def st_merge():     _run("st-merge")
def st_new():       _run("st-new")
def st_plot():      _run("st-plot")
def st_post():      _run("st-post")
def st_prep():      _run("st-prep")
def st_print():     _run("st-print")
def st_read():      _run("st-read")
def st_rm():        _run("st-rm")
def st_speak():     _run("st-speak")
def st_speed():     _run("st-speed")
def st_stones():    _run("st-stones")
def st_verdict():   _run("st-verdict")
def st_voice():     _run("st-voice")

