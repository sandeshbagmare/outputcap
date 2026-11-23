"""Tests for outputcap."""

import json

import pytest

from outputcap import Capped, cap, read_handle, slices


class TestSmallValues:
    def test_a_short_string_is_untouched(self):
        capped = cap("hello")
        assert capped.text == "hello"
        assert capped.truncated is False
        assert capped.note == ""
        assert capped.message() == "hello"

    def test_a_small_dict_becomes_json(self):
        capped = cap({"a": 1})
        assert json.loads(capped.text) == {"a": 1}
        assert capped.truncated is False

    def test_exactly_at_the_limit_is_not_truncated(self):
        assert cap("x" * 100, max_chars=100).truncated is False

    def test_one_over_the_limit_is_truncated(self):
        assert cap("x" * 101, max_chars=100).truncated is True

    def test_none(self):
        assert cap(None).text == "null"

    def test_bytes_are_decoded(self):
        assert cap(b"hello").text == "hello"

    def test_an_unserialisable_object(self):
        assert "object" in cap(object()).text

    def test_unicode_survives(self):
        assert cap({"k": "héllo"}).text.count("héllo") == 1


class TestTruncation:
    def test_long_text_is_cut_with_head_and_tail(self):
        text = "A" * 1000 + "MIDDLE" + "B" * 1000
        capped = cap(text, max_chars=200)
        assert capped.truncated is True
        assert capped.text.startswith("A")
        assert capped.text.endswith("B" * 10)
        assert "MIDDLE" not in capped.text
        assert capped.original_chars == len(text)

    def test_the_preview_fits_the_budget(self):
        capped = cap("x" * 10_000, max_chars=500)
        assert len(capped.text) <= 500 + 10

    def test_the_error_at_the_end_stays_visible(self):
        log = "ok\n" * 5000 + "ERROR: disk full\n"
        capped = cap(log, max_chars=200)
        assert "ERROR: disk full" in capped.text

    def test_the_note_reports_the_size(self):
        capped = cap("x" * 1000, max_chars=100)
        assert "1000 chars" in capped.note
        assert "truncated" in capped.note
        assert capped.note in capped.message()

    def test_head_and_tail_can_be_chosen(self):
        capped = cap("0123456789" * 20, max_chars=50, head=10, tail=5)
        assert capped.text.startswith("0123456789")
        assert capped.text.endswith("56789")
        assert capped.head_chars == 10
        assert capped.tail_chars == 5

    def test_a_tail_only_budget(self):
        capped = cap("x" * 500 + "TAIL", max_chars=100, head=0, tail=100)
        assert capped.text.endswith("TAIL")

    def test_a_head_only_budget(self):
        capped = cap("HEAD" + "x" * 500, max_chars=100, head=100, tail=0)
        assert capped.text.startswith("HEAD")
        assert "\n...\n" not in capped.text

    def test_a_tiny_budget(self):
        capped = cap("x" * 1000, max_chars=5)
        assert len(capped.text) <= 5
        assert capped.truncated is True

    def test_a_zero_budget_is_rejected(self):
        with pytest.raises(ValueError, match="max_chars"):
            cap("x", max_chars=0)


class TestReadingTheRest:
    def test_the_full_value_is_kept_in_memory(self):
        payload = {"rows": list(range(1000))}
        capped = cap(payload, max_chars=100)
        assert "999" in capped.read()
        assert capped.read(0, 1) == "{"

    def test_a_slice_of_the_full_text(self):
        capped = cap("0123456789" * 100, max_chars=50)
        assert capped.read(10, 15) == "01234"

    def test_a_string_is_readable_after_truncation(self):
        capped = cap("hello world", max_chars=4)
        assert capped.read() == "hello world"

    def test_slices_of_a_stored_output(self, tmp_path):
        capped = cap("x" * 5000, max_chars=100, directory=tmp_path)
        assert capped.handle is not None
        assert read_handle(capped.handle, 0, 5) == "xxxxx"

    def test_a_capped_value_with_no_truncation_reads_the_text(self):
        capped = cap("short")
        assert capped.read() == "short"


class TestStorage:
    def test_the_full_text_is_written_to_the_directory(self, tmp_path):
        text = "y" * 5000
        capped = cap(text, max_chars=100, directory=tmp_path / "outputs")
        assert capped.handle is not None
        assert capped.handle.parent.name == "outputs"
        assert capped.handle.read_text(encoding="utf-8") == text

    def test_the_note_includes_the_path(self, tmp_path):
        capped = cap("z" * 500, max_chars=50, directory=tmp_path)
        assert str(capped.handle) in capped.note

    def test_a_custom_file_name(self, tmp_path):
        capped = cap("z" * 500, max_chars=50, directory=tmp_path, name="read-1.txt")
        assert capped.handle.name == "read-1.txt"

    def test_the_handle_is_reported_in_json_form(self, tmp_path):
        capped = cap("z" * 500, max_chars=50, directory=tmp_path)
        payload = json.loads(json.dumps(capped.message()))
        assert str(capped.handle) in payload

    def test_a_small_value_is_not_stored(self, tmp_path):
        capped = cap("small", directory=tmp_path)
        assert capped.handle is None
        assert list(tmp_path.iterdir()) == []

    def test_a_missing_stored_file_raises(self, tmp_path):
        capped = cap({"a": 1}, max_chars=1, directory=tmp_path)
        capped.handle.unlink()
        with pytest.raises(FileNotFoundError, match="stored output is gone"):
            capped.read()


class TestSlices:
    def test_a_text_shorter_than_the_size(self):
        assert slices("abc", 10) == [(0, 3)]

    def test_an_exact_split(self):
        assert slices("abcdef", 3) == [(0, 3), (3, 6)]

    def test_with_an_overlap(self):
        assert slices("abcdef", 4, overlap=1) == [(0, 4), (3, 6)]

    def test_an_empty_text(self):
        assert slices("", 10) == []

    def test_a_size_of_zero_is_rejected(self):
        with pytest.raises(ValueError, match="size"):
            slices("abc", 0)

    def test_an_overlap_that_is_too_large(self):
        with pytest.raises(ValueError, match="overlap"):
            slices("abc", 3, overlap=3)

    def test_every_character_is_covered(self):
        text = "x" * 100
        covered = set()
        for start, end in slices(text, 30):
            covered.update(range(start, end))
        assert covered == set(range(100))


class TestCapped:
    def test_the_dataclass_holds_the_report(self):
        capped = Capped(text="a", truncated=False, original_chars=1)
        assert capped.head_chars == 0
        assert capped.note == ""


class TestCommandLine:
    def run(self, argv):
        from outputcap.__main__ import main

        return main(argv)

    def write(self, tmp_path, text, name="out.txt"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_text_file(self, tmp_path, capsys):
        path = self.write(tmp_path, "x" * 5000)
        assert self.run([path, "--max-chars", "100"]) == 0
        out = capsys.readouterr().out
        assert "truncated" in out
        assert len(out) < 300

    def test_json_is_prettified(self, tmp_path, capsys):
        path = self.write(tmp_path, json.dumps({"a": list(range(100))}), "out.json")
        assert self.run([path, "--max-chars", "80"]) == 0
        assert "truncated" in capsys.readouterr().out

    def test_note_only(self, tmp_path, capsys):
        path = self.write(tmp_path, "y" * 500)
        assert self.run([path, "--max-chars", "50", "--note-only"]) == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("[output truncated")

    def test_store(self, tmp_path, capsys):
        path = self.write(tmp_path, "z" * 500)
        store = tmp_path / "store"
        assert self.run([path, "--max-chars", "50", "--store", str(store)]) == 0
        stored = list(store.iterdir())
        assert len(stored) == 1
        assert stored[0].read_text(encoding="utf-8") == "z" * 500
        assert str(stored[0]) in capsys.readouterr().out

    def test_a_missing_file_exits_two(self, tmp_path, capsys):
        assert self.run([str(tmp_path / "nope.txt")]) == 2
        assert "cannot read" in capsys.readouterr().err

    def test_a_bad_budget_exits_two(self, tmp_path, capsys):
        path = self.write(tmp_path, "x")
        assert self.run([path, "--max-chars", "0"]) == 2
        assert "max_chars" in capsys.readouterr().err


class TestRigour:
    """Budget shapes and the paths that the first pass left untested."""

    def test_reading_a_stored_value_uses_the_file(self, tmp_path):
        capped = cap("q" * 900, max_chars=40, directory=tmp_path)
        assert capped.read(0, 3) == "qqq"
        assert len(capped.read()) == 900

    def test_a_tail_only_budget_that_is_not_enough(self):
        capped = cap("x" * 500, max_chars=100, tail=100)
        assert capped.tail_chars == 100
        assert capped.head_chars == 0
        assert capped.text.endswith("x")

    def test_head_and_tail_that_overflow_the_budget(self):
        capped = cap("0123456789" * 50, max_chars=60, head=50, tail=50)
        assert capped.head_chars == 50
        assert capped.tail_chars == 10

    def test_a_json_file_that_is_not_json_falls_back_to_text(self, tmp_path, capsys):
        from outputcap.__main__ import main

        path = tmp_path / "broken.json"
        path.write_text('{"a": ' + "x" * 300, encoding="utf-8")
        assert main([str(path), "--max-chars", "60"]) == 0
        assert "truncated" in capsys.readouterr().out

    def test_a_head_only_budget_without_a_tail_argument(self):
        capped = cap("0123456789" * 50, max_chars=100, head=60)
        assert capped.head_chars == 60
        assert capped.tail_chars == 40

    def test_slices_of_a_text_that_fits_exactly(self):
        assert slices("abcd", 4) == [(0, 4)]
        assert slices("x" * 5, 5, overlap=0) == [(0, 5)]
