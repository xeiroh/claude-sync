"""
Tests for path templating and replacement logic
"""

import pytest
from claude_sync.templates import ConfigTemplater
from claude_sync.profiles import ServerProfile


class TestConfigTemplater:
    """Test path templating and replacement"""

    @pytest.fixture
    def local_profile(self):
        """Local macOS profile"""
        return ServerProfile(
            name="local-mac",
            home="/Users/testuser",
            workspace="/Users/testuser/Projects",
            npm_global="/Users/testuser/.npm-global",
            install_method="npm",
            default_user="testuser",
            persistent_storage="/Users/testuser",
            platform="macos"
        )

    @pytest.fixture
    def remote_profile(self):
        """Remote Ubuntu profile"""
        return ServerProfile(
            name="remote-ubuntu",
            home="/home/ubuntu",
            workspace="/home/ubuntu/workspace",
            npm_global="/home/ubuntu/.npm-global",
            install_method="npm",
            default_user="ubuntu",
            persistent_storage="/home/ubuntu",
            platform="ubuntu"
        )

    @pytest.fixture
    def templater(self, local_profile, remote_profile):
        """Create templater with local and remote profiles"""
        # ConfigTemplater expects dicts, not ServerProfile objects
        return ConfigTemplater(local_profile.__dict__, remote_profile.__dict__)

    def test_direct_path_replacement(self, templater):
        """Test direct path replacement"""
        local_path = "/Users/testuser/.claude/settings.json"
        expected = "/home/ubuntu/.claude/settings.json"
        assert templater.template_config(local_path) == expected

    def test_file_protocol_replacement(self, templater):
        """Test file:// protocol path replacement"""
        local_path = "file:///Users/testuser/Projects/myproject"
        expected = "file:///home/ubuntu/workspace/myproject"
        assert templater.template_config(local_path) == expected

    def test_permission_pattern_replacement(self, templater):
        """Test permission pattern replacement (//path/**)"""
        local_path = "//Users/testuser/**"
        expected = "//home/ubuntu/**"
        assert templater.template_config(local_path) == expected

    def test_longest_path_first(self, templater):
        """Test that longest paths are replaced first to avoid partial replacements"""
        # /Users/testuser/Projects should be replaced before /Users/testuser
        local_path = "/Users/testuser/Projects/myfile.txt"
        expected = "/home/ubuntu/workspace/myfile.txt"
        result = templater.template_config(local_path)
        assert result == expected
        # Should NOT be /home/ubuntu/Projects/myfile.txt

    def test_workspace_path_priority(self, templater):
        """Test workspace paths take priority over home paths"""
        local_path = "/Users/testuser/Projects/repo/file.txt"
        expected = "/home/ubuntu/workspace/repo/file.txt"
        assert templater.template_config(local_path) == expected

    def test_no_replacement_for_unmatched_paths(self, templater):
        """Test paths that don't match any mapping remain unchanged"""
        local_path = "/opt/homebrew/bin/node"
        assert templater.template_config(local_path) == local_path

    def test_template_dict_recursive(self, templater):
        """Test recursive dictionary templating"""
        config = {
            "path": "/Users/testuser/.claude",
            "nested": {
                "path": "/Users/testuser/Projects/myproject",
                "other": "unchanged"
            },
            "list": [
                "/Users/testuser/file1.txt",
                "/Users/testuser/file2.txt"
            ]
        }

        result = templater.template_config(config)

        assert result["path"] == "/home/ubuntu/.claude"
        assert result["nested"]["path"] == "/home/ubuntu/workspace/myproject"
        assert result["nested"]["other"] == "unchanged"
        assert result["list"][0] == "/home/ubuntu/file1.txt"
        assert result["list"][1] == "/home/ubuntu/file2.txt"

    def test_template_list(self, templater):
        """Test list templating"""
        paths = [
            "/Users/testuser/path1",
            "/Users/testuser/Projects/path2",
            "unchanged"
        ]

        result = templater.template_config(paths)

        assert result[0] == "/home/ubuntu/path1"
        assert result[1] == "/home/ubuntu/workspace/path2"
        assert result[2] == "unchanged"

    def test_extract_local_paths(self, templater):
        """Test extraction of local paths from strings"""
        text = "Some text with /Users/testuser/path and /Users/testuser/Projects/file"
        paths = templater.extract_local_paths(text)

        # extract_local_paths returns the actual found paths, not the mappings
        assert len(paths) >= 2

    def test_npm_global_path_replacement(self, templater):
        """Test npm global path replacement"""
        local_path = "/Users/testuser/.npm-global/bin/something"
        expected = "/home/ubuntu/.npm-global/bin/something"
        assert templater.template_config(local_path) == expected

    def test_multiple_paths_in_string(self, templater):
        """Test string with multiple paths"""
        text = "Export PATH=/Users/testuser/.npm-global/bin:/Users/testuser/bin"
        result = templater.template_config(text)
        assert "/home/ubuntu/.npm-global/bin" in result
        assert "/home/ubuntu/bin" in result

    def test_permission_double_slash_preserved(self, templater):
        """Test that double slash in permissions is preserved"""
        permission = "Read(//Users/testuser/**)"
        result = templater.template_config(permission)
        assert result == "Read(//home/ubuntu/**)"
        assert "//" in result  # Double slash preserved
