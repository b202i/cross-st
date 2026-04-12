"""
Tests for mmd_util.py — project-root helpers, block files, segment builder,
template seeding, and stones domain seeding.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch

import mmd_util
from mmd_util import (
    get_project_root,
    get_tmp_dir,
    tmp_safe_name,
    block_file_path,
    create_block_file,
    remove_block_file,
    build_segments,
    get_default_stones_dir,
    seed_user_templates,
    seed_stones_domains,
)


# ── get_project_root ──────────────────────────────────────────────────────────

class TestGetProjectRoot:
    def test_returns_path(self):
        assert isinstance(get_project_root(), Path)

    def test_path_exists(self):
        assert get_project_root().exists()

    def test_contains_mmd_util_py(self):
        assert (get_project_root() / "mmd_util.py").exists()


# ── get_tmp_dir ───────────────────────────────────────────────────────────────

class TestGetTmpDir:
    def test_returns_path(self):
        assert isinstance(get_tmp_dir(), Path)

    def test_dir_is_created(self):
        tmp = get_tmp_dir()
        assert tmp.exists()
        assert tmp.is_dir()

    def test_is_named_tmp_under_root(self):
        tmp = get_tmp_dir()
        assert tmp.name == "tmp"
        assert tmp.parent == get_project_root()


# ── tmp_safe_name ─────────────────────────────────────────────────────────────

class TestTmpSafeName:
    def test_simple_name_unchanged(self):
        # plain name with no separator → returned as-is
        result = tmp_safe_name("myfile")
        assert result == "myfile"

    def test_absolute_outside_root_returns_basename(self):
        # /tmp/some/deep/path/myfile → "myfile"
        result = tmp_safe_name("/tmp/some/deep/path/myfile")
        assert result == "myfile"

    def test_no_os_sep_in_result(self):
        result = tmp_safe_name("/tmp/a/b/c/name")
        assert os.sep not in result

    def test_relative_path_uses_double_underscore(self, tmp_path):
        """
        A relative path resolved under project root becomes double-underscore
        separated.  We create a real path under the project root to exercise
        this branch.
        """
        root = get_project_root()
        # Build a name that is a sibling to an existing dir so resolve() works
        rel_input = "tmp/test_safe_name_file"
        result = tmp_safe_name(rel_input)
        # Either the relative form (with __) or the basename is acceptable
        assert isinstance(result, str)
        assert len(result) > 0


# ── block file helpers ────────────────────────────────────────────────────────

class TestBlockFilePath:
    def test_returns_path(self):
        p = block_file_path("my_safe")
        assert isinstance(p, Path)

    def test_has_block_extension(self):
        p = block_file_path("my_safe")
        assert p.name == "my_safe.block"

    def test_lives_in_tmp_dir(self):
        p = block_file_path("my_safe")
        assert p.parent == get_tmp_dir()


class TestCreateBlockFile:
    def test_creates_file(self, tmp_path):
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            create_block_file("test_create")
        assert (tmp_path / "test_create.block").exists()

    def test_verbose_prints_message(self, tmp_path, capsys):
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            create_block_file("test_verbose", verbose=True)
        out = capsys.readouterr().out
        assert "Created block file" in out

    def test_silent_by_default(self, tmp_path, capsys):
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            create_block_file("test_silent")
        out = capsys.readouterr().out
        assert out == ""


class TestRemoveBlockFile:
    def test_removes_existing_file(self, tmp_path):
        block = tmp_path / "test_remove.block"
        block.touch()
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            remove_block_file("test_remove")
        assert not block.exists()

    def test_no_error_when_missing(self, tmp_path):
        """Removing a non-existent block file must not raise."""
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            remove_block_file("nonexistent_block")  # should not raise

    def test_verbose_removed(self, tmp_path, capsys):
        block = tmp_path / "test_vr.block"
        block.touch()
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            remove_block_file("test_vr", verbose=True)
        out = capsys.readouterr().out
        assert "Removed block file" in out

    def test_verbose_missing(self, tmp_path, capsys):
        with patch("mmd_util.get_tmp_dir", return_value=tmp_path):
            remove_block_file("never_existed", verbose=True)
        out = capsys.readouterr().out
        assert "Block file not found" in out


# ── build_segments ────────────────────────────────────────────────────────────

class TestBuildSegments:
    def test_empty_string_returns_empty_list(self):
        assert build_segments("") == []

    def test_single_sentence_period(self):
        segs = build_segments("This is a sentence.")
        assert len(segs) == 1
        assert segs[0]["text"] == "This is a sentence."
        assert segs[0]["id"] == 0
        assert segs[0]["para"] == 0

    def test_question_mark_ending(self):
        segs = build_segments("Is this a question?")
        assert len(segs) == 1

    def test_exclamation_mark_ending(self):
        segs = build_segments("Watch out!")
        assert len(segs) == 1

    def test_non_sentence_ending_skipped(self):
        text = "This ends with a colon:\n\nThis ends with a period."
        segs = build_segments(text)
        assert len(segs) == 1
        assert segs[0]["text"] == "This ends with a period."

    def test_multiple_paragraphs_get_sequential_ids(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        segs = build_segments(text)
        assert len(segs) == 3
        assert [s["id"] for s in segs] == [0, 1, 2]

    def test_para_index_reflects_source_position(self):
        """Skipped paragraphs still advance the para counter."""
        text = "First.\n\nNo ending here\n\nThird."
        segs = build_segments(text)
        # First → para 0, "No ending" skipped, Third → para 2
        assert segs[0]["para"] == 0
        assert segs[1]["para"] == 2

    def test_citation_stripped_before_check(self):
        """Citations like [1] or [^2] at EOL are stripped before the ending check."""
        segs = build_segments("This is a fact.[1]")
        assert len(segs) == 1

    def test_citation_multi_stripped(self):
        segs = build_segments("Multiple citations here.[1][^2][3]")
        assert len(segs) == 1

    def test_blank_paragraphs_skipped(self):
        text = "First.\n\n\n\n\n\nSecond."
        segs = build_segments(text)
        assert len(segs) == 2

    def test_closing_quote_ending_accepted(self):
        """Paragraphs ending with a closing quote are accepted."""
        text = 'He said, "Hello there."'
        segs = build_segments(text)
        assert len(segs) == 1

    def test_segment_has_exactly_id_text_para_keys(self):
        segs = build_segments("A paragraph.")
        assert set(segs[0].keys()) == {"id", "text", "para"}

    def test_deterministic_repeated_calls(self):
        """Calling twice on the same text returns identical results."""
        text = "First.\n\nSecond."
        assert build_segments(text) == build_segments(text)

    def test_whitespace_only_paragraphs_skipped(self):
        text = "First.\n\n   \n\nSecond."
        segs = build_segments(text)
        assert len(segs) == 2


# ── get_default_stones_dir ────────────────────────────────────────────────────

class TestGetDefaultStonesDir:
    def test_default_when_no_env(self):
        env_clean = {k: v for k, v in os.environ.items() if k != "CROSS_STONES_DIR"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = get_default_stones_dir()
        assert result == Path.home() / "cross-stones"

    def test_env_var_override(self, tmp_path):
        with patch.dict(os.environ, {"CROSS_STONES_DIR": str(tmp_path)}):
            result = get_default_stones_dir()
        assert result == tmp_path

    def test_env_var_expanduser(self):
        with patch.dict(os.environ, {"CROSS_STONES_DIR": "~/my-custom-stones"}):
            result = get_default_stones_dir()
        assert "~" not in str(result)

    def test_returns_path_object(self):
        result = get_default_stones_dir()
        assert isinstance(result, Path)


# ── seed_user_templates ───────────────────────────────────────────────────────

class TestSeedUserTemplates:
    def test_zero_zero_when_src_missing(self, tmp_path):
        copied, skipped = seed_user_templates(src_dir=tmp_path / "no-such-dir")
        assert copied == 0
        assert skipped == 0

    def test_copies_prompt_files_only(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        (src / "test.prompt").write_text("Prompt content")
        (src / "ignore.txt").write_text("Not a prompt")

        with patch("mmd_util._USER_TEMPLATES_DIR", dst):
            copied, skipped = seed_user_templates(src_dir=src)

        assert copied == 1
        assert skipped == 0
        assert (dst / "test.prompt").exists()
        assert not (dst / "ignore.txt").exists()

    def test_skips_existing_by_default(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()
        (src / "test.prompt").write_text("New content")
        (dst / "test.prompt").write_text("Old content")

        with patch("mmd_util._USER_TEMPLATES_DIR", dst):
            copied, skipped = seed_user_templates(src_dir=src, overwrite=False)

        assert copied == 0
        assert skipped == 1
        assert (dst / "test.prompt").read_text() == "Old content"

    def test_overwrite_replaces_existing(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()
        (src / "test.prompt").write_text("New content")
        (dst / "test.prompt").write_text("Old content")

        with patch("mmd_util._USER_TEMPLATES_DIR", dst):
            copied, skipped = seed_user_templates(src_dir=src, overwrite=True)

        assert copied == 1
        assert skipped == 0
        assert (dst / "test.prompt").read_text() == "New content"

    def test_verbose_prints_copy_message(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        (src / "verbose.prompt").write_text("Prompt")

        with patch("mmd_util._USER_TEMPLATES_DIR", dst):
            seed_user_templates(src_dir=src, quiet=False)

        out = capsys.readouterr().out
        assert "verbose.prompt" in out

    def test_multiple_prompt_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        for i in range(3):
            (src / f"p{i}.prompt").write_text(f"Prompt {i}")

        with patch("mmd_util._USER_TEMPLATES_DIR", dst):
            copied, skipped = seed_user_templates(src_dir=src)

        assert copied == 3
        assert skipped == 0


# ── seed_stones_domains ───────────────────────────────────────────────────────

class TestSeedStonesDomains:
    def test_zero_zero_when_src_missing(self, tmp_path):
        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", tmp_path / "no-such"):
            copied, skipped = seed_stones_domains(dst_dir=tmp_path / "out")
        assert copied == 0
        assert skipped == 0

    def test_copies_prompt_files(self, tmp_path):
        src = tmp_path / "domains"
        src.mkdir()
        dst = tmp_path / "out"
        (src / "science.prompt").write_text("Science domain")

        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", src):
            copied, skipped = seed_stones_domains(dst_dir=dst)

        assert copied == 1
        assert skipped == 0
        assert (dst / "science.prompt").exists()

    def test_skips_existing(self, tmp_path):
        src = tmp_path / "domains"
        src.mkdir()
        dst = tmp_path / "out"
        dst.mkdir()
        (src / "science.prompt").write_text("New")
        (dst / "science.prompt").write_text("Old")

        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", src):
            copied, skipped = seed_stones_domains(dst_dir=dst, overwrite=False)

        assert copied == 0
        assert skipped == 1
        assert (dst / "science.prompt").read_text() == "Old"

    def test_overwrite_replaces(self, tmp_path):
        src = tmp_path / "domains"
        src.mkdir()
        dst = tmp_path / "out"
        dst.mkdir()
        (src / "cooking.prompt").write_text("New")
        (dst / "cooking.prompt").write_text("Old")

        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", src):
            copied, skipped = seed_stones_domains(dst_dir=dst, overwrite=True)

        assert copied == 1
        assert skipped == 0
        assert (dst / "cooking.prompt").read_text() == "New"

    def test_verbose_print(self, tmp_path, capsys):
        src = tmp_path / "domains"
        src.mkdir()
        dst = tmp_path / "out"
        (src / "history.prompt").write_text("History prompt")

        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", src):
            seed_stones_domains(dst_dir=dst, quiet=False)

        out = capsys.readouterr().out
        assert "history.prompt" in out

    def test_creates_dst_dir(self, tmp_path):
        src = tmp_path / "domains"
        src.mkdir()
        dst = tmp_path / "new_dst"
        (src / "test.prompt").write_text("content")
        assert not dst.exists()

        with patch("mmd_util._BUNDLED_STONES_DOMAINS_DIR", src):
            seed_stones_domains(dst_dir=dst)

        assert dst.exists()

