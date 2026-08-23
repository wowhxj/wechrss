from pathlib import Path

from scripts.bootstrap import build_parser, dependency_fingerprint, venv_python


def test_dependency_fingerprint_changes_with_input(tmp_path: Path):
    first = tmp_path / "requirements.txt"
    second = tmp_path / "VERSION"
    first.write_text("example==1\n", encoding="utf-8")
    second.write_text("1.0.0\n", encoding="utf-8")
    before = dependency_fingerprint(first, second)
    second.write_text("1.0.1\n", encoding="utf-8")
    assert dependency_fingerprint(first, second) != before


def test_bootstrap_defaults_and_venv_path(tmp_path: Path):
    args = build_parser().parse_args([])
    assert (args.host, args.port, args.no_open) == ("127.0.0.1", 8080, False)
    assert venv_python(tmp_path).name in {"python", "python.exe"}
