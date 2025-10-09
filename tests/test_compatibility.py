"""
Tests for compatibility checking and config sanitization
"""

import pytest
import tempfile
import json
from pathlib import Path
from claude_sync.compatibility import CompatibilityChecker


class TestCompatibilityChecker:
    """Test config sanitization and compatibility validation"""

    @pytest.fixture
    def local_profile(self):
        """Local macOS profile"""
        return {
            "home": "/Users/testuser",
            "workspace": "/Users/testuser/Projects",
            "npm_global": "/Users/testuser/.npm-global",
            "install_method": "npm",
            "persistent_storage": "/Users/testuser"
        }

    @pytest.fixture
    def remote_profile(self):
        """Remote Ubuntu profile"""
        return {
            "home": "/home/ubuntu",
            "workspace": "/home/ubuntu/workspace",
            "npm_global": "/home/ubuntu/.npm-global",
            "install_method": "npm",
            "persistent_storage": "/home/ubuntu"
        }

    @pytest.fixture
    def checker(self, local_profile, remote_profile):
        """Create CompatibilityChecker"""
        return CompatibilityChecker(local_profile, remote_profile)

    def test_should_skip_projects(self, checker):
        """Test that 'projects' directory is skipped"""
        assert not checker.should_sync_item("projects")

    def test_should_skip_todos(self, checker):
        """Test that 'todos' directory is skipped"""
        assert not checker.should_sync_item("todos")

    def test_should_skip_logs(self, checker):
        """Test that 'logs' directory is skipped"""
        assert not checker.should_sync_item("logs")

    def test_should_skip_shell_snapshots(self, checker):
        """Test that 'shell-snapshots' directory is skipped"""
        assert not checker.should_sync_item("shell-snapshots")

    def test_should_skip_ide(self, checker):
        """Test that 'ide' directory is skipped"""
        assert not checker.should_sync_item("ide")

    def test_should_skip_statsig(self, checker):
        """Test that 'statsig' directory is skipped"""
        assert not checker.should_sync_item("statsig")

    def test_should_skip_jsonl_files(self, checker):
        """Test that .jsonl files are skipped"""
        assert not checker.should_sync_item("chat.jsonl")
        assert not checker.should_sync_item("history.jsonl")

    def test_should_sync_agents(self, checker):
        """Test that 'agents' directory is synced"""
        assert checker.should_sync_item("agents")

    def test_should_sync_commands(self, checker):
        """Test that 'commands' directory is synced"""
        assert checker.should_sync_item("commands")

    def test_should_sync_settings(self, checker):
        """Test that 'settings.json' is synced"""
        assert checker.should_sync_item("settings.json")

    def test_should_sync_md_files(self, checker):
        """Test that .md files are synced"""
        assert checker.should_sync_item("CLAUDE.md")
        assert checker.should_sync_item("README.md")
        assert checker.should_sync_item("MODE_DeepResearch.md")

    def test_sanitize_claude_json_removes_projects(self, checker, tmp_path):
        """Test that 'projects' key is removed from .claude.json"""
        claude_json = tmp_path / ".claude.json"
        config = {
            "installMethod": "npm",
            "projects": {
                "local-project-1": "/Users/testuser/Projects/proj1",
                "local-project-2": "/Users/testuser/Projects/proj2"
            },
            "mcpServers": {
                "test-server": {"command": "npx"}
            }
        }

        with open(claude_json, "w") as f:
            json.dump(config, f)

        result = checker.sanitize_claude_json(claude_json)

        assert "projects" not in result
        assert "installMethod" in result
        assert "mcpServers" in result

    def test_sanitize_claude_json_templates_paths(self, checker, tmp_path):
        """Test that paths in .claude.json are templated"""
        claude_json = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "test-server": {
                    "command": "node",
                    "args": ["/Users/testuser/Projects/server.js"]
                }
            }
        }

        with open(claude_json, "w") as f:
            json.dump(config, f)

        result = checker.sanitize_claude_json(claude_json)

        # Path should be templated
        assert "/home/ubuntu/workspace/server.js" in result["mcpServers"]["test-server"]["args"]
        assert "/Users/testuser" not in str(result)

    def test_check_install_method_same(self, checker):
        """Test install method compatibility when same"""
        assert checker.check_install_method("npm", "npm") is True

    def test_check_install_method_npm_native_compatible(self, checker):
        """Test that npm and native are compatible"""
        assert checker.check_install_method("npm", "native") is True
        assert checker.check_install_method("native", "npm") is True

    def test_check_install_method_incompatible(self, checker):
        """Test incompatible install methods"""
        # pip vs npm would be incompatible (though Claude Code doesn't use pip)
        assert checker.check_install_method("pip", "npm") is False

    def test_validate_mcp_server_clean(self, checker):
        """Test MCP server validation with clean config"""
        mcp_config = {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem"]
        }

        is_compatible, issues = checker.validate_mcp_server("filesystem", mcp_config)

        assert is_compatible is True
        assert len(issues) == 0

    def test_validate_mcp_server_absolute_path_command(self, checker):
        """Test MCP server validation with absolute path in command"""
        mcp_config = {
            "command": "/usr/local/bin/custom-server",
            "args": []
        }

        is_compatible, issues = checker.validate_mcp_server("custom", mcp_config)

        assert is_compatible is False
        assert len(issues) > 0
        assert any("absolute path" in issue.lower() for issue in issues)

    def test_validate_mcp_server_local_path_in_args(self, checker):
        """Test MCP server validation with local path in args"""
        mcp_config = {
            "command": "node",
            "args": ["/Users/testuser/custom-server.js"]
        }

        is_compatible, issues = checker.validate_mcp_server("custom", mcp_config)

        assert is_compatible is False
        assert len(issues) > 0
        assert any("local path" in issue.lower() for issue in issues)

    def test_process_file_for_sync_json(self, checker, tmp_path):
        """Test processing JSON file for sync"""
        json_file = tmp_path / "config.json"
        config = {
            "path": "/Users/testuser/mypath",
            "value": "unchanged"
        }

        with open(json_file, "w") as f:
            json.dump(config, f)

        result = checker.process_file_for_sync(json_file)

        assert isinstance(result, dict)
        assert result["path"] == "/home/ubuntu/mypath"
        assert result["value"] == "unchanged"

    def test_process_file_for_sync_markdown(self, checker, tmp_path):
        """Test processing markdown file for sync"""
        md_file = tmp_path / "CLAUDE.md"
        content = "# Test\n\nPath: /Users/testuser/Projects\n"

        with open(md_file, "w") as f:
            f.write(content)

        result = checker.process_file_for_sync(md_file)

        assert isinstance(result, str)
        assert "/home/ubuntu/workspace" in result
        assert "/Users/testuser" not in result

    def test_sanitize_settings_json_templates_paths(self, checker, tmp_path):
        """Test that settings.json paths are templated"""
        settings_json = tmp_path / "settings.json"
        settings = {
            "approvedToolUses": {
                "Read": ["//Users/testuser/**"]
            }
        }

        with open(settings_json, "w") as f:
            json.dump(settings, f)

        result = checker.sanitize_settings_json(settings_json)

        # Permission paths should be templated
        assert result["approvedToolUses"]["Read"][0] == "//home/ubuntu/**"

    def test_get_sync_plan_separates_files(self, checker, tmp_path):
        """Test that get_sync_plan separates files to sync vs skip"""
        # Create test directory structure
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        (claude_dir / "agents").mkdir()
        (claude_dir / "commands").mkdir()
        (claude_dir / "projects").mkdir()  # Should be skipped
        (claude_dir / "settings.json").touch()
        (claude_dir / "chat.jsonl").touch()  # Should be skipped

        files_to_sync, files_to_skip = checker.get_sync_plan(claude_dir)

        # Check synced items
        sync_names = [f.name for f in files_to_sync]
        assert "agents" in sync_names
        assert "commands" in sync_names
        assert "settings.json" in sync_names

        # Check skipped items
        skip_names = [f.name for f in files_to_skip]
        assert "projects" in skip_names
        assert "chat.jsonl" in skip_names
