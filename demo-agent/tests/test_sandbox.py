"""The demo sandbox must hold even when Guardian allows something it shouldn't."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sandbox_tools as sb  # noqa: E402


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "WORKSPACE", tmp_path / "workspace")
    sb.reset_workspace()
    return sb.WORKSPACE


@pytest.mark.parametrize("path", ["../outside.txt", "../../etc/passwd", "C:/Windows/win.ini", "/etc/passwd"])
def test_file_tools_refuse_paths_outside_the_workspace(path):
    for call in (
        lambda: sb.read_file.invoke({"path": path}),
        lambda: sb.write_file.invoke({"path": path, "content": "x"}),
        lambda: sb.delete_file.invoke({"path": path}),
    ):
        with pytest.raises(ValueError, match="outside the sandbox"):
            call()


def test_destructive_shell_commands_are_refused(workspace):
    before = sorted(p.name for p in workspace.iterdir())
    out = sb.run_shell.invoke({"command": "rm -rf ./*"})
    assert out.startswith("[sandbox] refused")
    assert sorted(p.name for p in workspace.iterdir()) == before


@pytest.mark.parametrize("command", ["ls; rm -rf ./*", "cat README.md | head", "echo x > app/greeter.py",
                                     "ls && cat README.md", "echo $(whoami)"])
def test_one_command_at_a_time(command):
    assert "one command at a time" in sb.run_shell.invoke({"command": command})


def test_ls_lists_folders_and_names_files():
    assert sb.run_shell.invoke({"command": "ls -la app README.md"}) == "app:\napp/greeter.py\n\nREADME.md"
    assert "No such file" in sb.run_shell.invoke({"command": "ls missing"})


def test_python_scripts_are_screened(workspace):
    (workspace / "evil.py").write_text("import shutil\nshutil.rmtree('/')\n")
    assert "refused" in sb.run_shell.invoke({"command": "python evil.py"})
    assert sb.run_shell.invoke({"command": "python app/greeter.py"}) == "Helo, world!"


def test_migration_runs_inside_the_workspace(workspace):
    assert "migrated 3" in sb.run_shell.invoke({"command": "python scripts/migrate_db.py --apply"})
    assert '"plan": "free"' in (workspace / "data/users.json").read_text()


def test_http_only_sends_get():
    out = sb.http_request.invoke({"url": "https://example.com", "method": "POST", "body": "x"})
    assert out.startswith("[sandbox] refused")
