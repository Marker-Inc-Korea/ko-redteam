from probes.cli import main


def test_help_lists_common_workflows(capsys) -> None:
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "qualify" in output
    assert "self-check" in output
    assert "Existing ko-redteam-* commands remain supported" in output


def test_unknown_command_fails_without_traceback(capsys) -> None:
    assert main(["unknown"]) == 2
    assert "unknown command" in capsys.readouterr().err
