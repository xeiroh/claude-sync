"""
Tests for sync manager and SSH operations
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from claude_sync.sync import SyncManager
from claude_sync.profiles import ProfileManager, ServerProfile


class TestSyncManager:
    """Test sync manager functionality"""

    @pytest.fixture
    def local_profile(self):
        """Local profile"""
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
    def profile_manager(self):
        """Mock profile manager"""
        manager = Mock(spec=ProfileManager)
        manager.get_profile = Mock(return_value=Mock(spec=ServerProfile))
        return manager

    @pytest.fixture
    def sync_manager(self, profile_manager, local_profile):
        """Create SyncManager"""
        return SyncManager(
            profile_manager=profile_manager,
            local_profile=local_profile,
            dry_run=True,
            verbose=False
        )

    def test_parse_ssh_target_user_and_host(self, sync_manager):
        """Test parsing SSH target with user@host format"""
        host, port, username = sync_manager._parse_ssh_target("john@example.com")

        assert host == "example.com"
        assert port == 22
        assert username == "john"

    def test_parse_ssh_target_with_port(self, sync_manager):
        """Test parsing SSH target with user@host:port format"""
        host, port, username = sync_manager._parse_ssh_target("john@example.com:2222")

        assert host == "example.com"
        assert port == 2222
        assert username == "john"

    def test_parse_ssh_target_host_only(self, sync_manager, monkeypatch):
        """Test parsing SSH target with only hostname"""
        monkeypatch.setenv("USER", "currentuser")

        host, port, username = sync_manager._parse_ssh_target("example.com")

        assert host == "example.com"
        assert port == 22
        assert username == "currentuser"

    def test_parse_ssh_target_host_with_port_no_user(self, sync_manager, monkeypatch):
        """Test parsing SSH target with host:port but no user"""
        monkeypatch.setenv("USER", "currentuser")

        host, port, username = sync_manager._parse_ssh_target("example.com:3000")

        assert host == "example.com"
        assert port == 3000
        assert username == "currentuser"

    @patch('subprocess.run')
    def test_get_local_claude_version_success(self, mock_run, sync_manager):
        """Test getting local Claude Code version successfully"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "claude-code 2.0.5\n"
        mock_run.return_value = mock_result

        version = sync_manager._get_local_claude_version()

        assert version == "2.0.5"
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_get_local_claude_version_not_found(self, mock_run, sync_manager):
        """Test getting local version when Claude Code not installed"""
        mock_run.side_effect = FileNotFoundError()

        version = sync_manager._get_local_claude_version()

        assert version is None

    @patch('subprocess.run')
    def test_get_local_claude_version_version_only(self, mock_run, sync_manager):
        """Test getting version when output is just version number"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "2.0.5\n"
        mock_run.return_value = mock_result

        version = sync_manager._get_local_claude_version()

        assert version == "2.0.5"

    @patch('subprocess.run')
    def test_get_local_claude_version_from_stderr(self, mock_run, sync_manager):
        """Test getting version when CLI writes to stderr"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "claude-code 2.0.5\n"
        mock_run.return_value = mock_result

        version = sync_manager._get_local_claude_version()

        assert version == "2.0.5"

    def test_check_remote_claude_installation_installed(self, sync_manager):
        """Test checking remote Claude Code when installed"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b"claude-code 2.0.5"
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        is_installed, version = sync_manager._check_remote_claude_installation(mock_ssh)

        assert is_installed is True
        assert version == "2.0.5"

    def test_check_remote_claude_installation_not_found(self, sync_manager):
        """Test checking remote Claude Code when not installed"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stderr = Mock()
        mock_stderr.read.return_value = b"command not found"
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        is_installed, version = sync_manager._check_remote_claude_installation(mock_ssh)

        assert is_installed is False
        assert version is None

    def test_check_remote_claude_installation_version_in_stderr(self, sync_manager):
        """Test remote check when version output is sent to stderr"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stderr = Mock()
        mock_stderr.read.return_value = b"claude-code v2.0.5"
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        is_installed, version = sync_manager._check_remote_claude_installation(mock_ssh)

        assert is_installed is True
        assert version == "2.0.5"

    @patch('claude_sync.sync.SyncManager._check_remote_claude_installation')
    def test_install_claude_code_remote_npm(self, mock_check, sync_manager):
        """Test installing Claude Code remotely via npm"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        # Mock successful verification
        mock_check.return_value = (True, "2.0.5")

        success = sync_manager._install_claude_code_remote(
            mock_ssh,
            "npm",
            "2.0.5"
        )

        assert success is True
        # Verify correct npm command was used (check first call)
        first_call_args = mock_ssh.exec_command.call_args_list[0][0][0]
        assert "npm install -g @anthropic-ai/claude-code@2.0.5" in first_call_args

    @patch('claude_sync.sync.SyncManager._check_remote_claude_installation')
    def test_install_claude_code_remote_native(self, mock_check, sync_manager):
        """Test installing Claude Code remotely via native installer"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b"2.0.5"  # Verification output
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        # Mock successful verification
        mock_check.return_value = (True, "2.0.5")

        success = sync_manager._install_claude_code_remote(
            mock_ssh,
            "native",
            "2.0.5"
        )

        assert success is True
        # Verify correct native command was used (check first call)
        first_call_args = mock_ssh.exec_command.call_args_list[0][0][0]
        assert "curl -fsSL https://claude.ai/install.sh" in first_call_args
        assert "bash -s 2.0.5" in first_call_args

    @patch('claude_sync.sync.SyncManager._check_remote_claude_installation')
    def test_install_claude_code_remote_failure(self, mock_check, sync_manager):
        """Test installation failure handling - continues with sync"""
        mock_ssh = Mock()
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = Mock()
        mock_stderr.read.return_value = b"Installation failed"
        mock_ssh.exec_command.return_value = (None, mock_stdout, mock_stderr)

        success = sync_manager._install_claude_code_remote(
            mock_ssh,
            "npm",
            "2.0.5"
        )

        # Should return True to continue with sync even if installation fails
        assert success is True

    def test_install_claude_code_remote_unknown_method(self, sync_manager):
        """Test installation with unknown install method"""
        mock_ssh = Mock()

        success = sync_manager._install_claude_code_remote(
            mock_ssh,
            "unknown-method",
            "2.0.5"
        )

        assert success is False

    def test_validate_compatibility_no_issues(self, sync_manager):
        """Test compatibility validation with no issues"""
        mock_checker = Mock()
        mock_checker.check_install_method.return_value = True
        mock_checker.validate_mcp_server.return_value = (True, [])
        mock_checker.remote_profile = {"install_method": "npm"}

        configs = {
            "claude_json": {
                "installMethod": "npm",
                "mcpServers": {
                    "test-server": {"command": "npx"}
                }
            }
        }

        result = sync_manager._validate_compatibility(mock_checker, configs)

        assert result is True

    def test_validate_compatibility_install_method_mismatch(self, sync_manager):
        """Test compatibility validation with install method mismatch"""
        mock_checker = Mock()
        mock_checker.check_install_method.return_value = False
        mock_checker.remote_profile = {"install_method": "native"}

        configs = {
            "claude_json": {
                "installMethod": "npm"
            }
        }

        # Should return True (warning, not error)
        result = sync_manager._validate_compatibility(mock_checker, configs)

        assert result is True

    def test_validate_compatibility_mcp_server_issues(self, sync_manager):
        """Test compatibility validation with MCP server issues"""
        mock_checker = Mock()
        mock_checker.check_install_method.return_value = True
        mock_checker.validate_mcp_server.return_value = (False, ["Issue 1", "Issue 2"])
        mock_checker.remote_profile = {"install_method": "npm"}

        configs = {
            "claude_json": {
                "installMethod": "npm",
                "mcpServers": {
                    "problematic-server": {"command": "/absolute/path/to/command"}
                }
            }
        }

        # Should return True (warnings, not errors)
        result = sync_manager._validate_compatibility(mock_checker, configs)

        assert result is True

    def test_add_to_path_in_shell_rc_bashrc_exists(self, sync_manager):
        """Test adding PATH to existing .bashrc"""
        mock_ssh = Mock()

        # Mock .bashrc exists, PATH not already present
        def exec_command_side_effect(cmd):
            mock_stdout = Mock()
            if 'test -f ~/.bashrc' in cmd:
                mock_stdout.read.return_value = b"exists"
            elif 'grep -q' in cmd:
                mock_stdout.read.return_value = b""  # PATH not found
            else:
                mock_stdout.read.return_value = b""

            mock_stdout.channel.recv_exit_status.return_value = 0
            mock_stderr = Mock()
            mock_stderr.read.return_value = b""
            return (None, mock_stdout, mock_stderr)

        mock_ssh.exec_command.side_effect = exec_command_side_effect

        sync_manager._add_to_path_in_shell_rc(mock_ssh, '$HOME/.local/bin')

        # Verify PATH was added to .bashrc
        calls = [str(call) for call in mock_ssh.exec_command.call_args_list]
        assert any('.bashrc' in call and 'export PATH' in call for call in calls)

    def test_add_to_path_in_shell_rc_path_already_exists(self, sync_manager):
        """Test skipping PATH addition when already present"""
        mock_ssh = Mock()

        # Mock .bashrc exists, PATH already present
        def exec_command_side_effect(cmd):
            mock_stdout = Mock()
            if 'test -f ~/.bashrc' in cmd:
                mock_stdout.read.return_value = b"exists"
            elif 'grep -q' in cmd:
                mock_stdout.read.return_value = b"found"  # PATH already exists
            else:
                mock_stdout.read.return_value = b""

            mock_stdout.channel.recv_exit_status.return_value = 0
            mock_stderr = Mock()
            mock_stderr.read.return_value = b""
            return (None, mock_stdout, mock_stderr)

        mock_ssh.exec_command.side_effect = exec_command_side_effect

        sync_manager._add_to_path_in_shell_rc(mock_ssh, '$HOME/.local/bin')

        # Verify no PATH addition command was executed
        calls = [str(call) for call in mock_ssh.exec_command.call_args_list]
        assert not any('echo' in call and 'export PATH' in call and '>>' in call for call in calls)

    def test_add_to_path_in_shell_rc_no_rc_file(self, sync_manager):
        """Test creating .bashrc when no RC file exists"""
        mock_ssh = Mock()

        # Mock no RC files exist
        def exec_command_side_effect(cmd):
            mock_stdout = Mock()
            if 'test -f' in cmd:
                mock_stdout.read.return_value = b""  # No RC files exist
            else:
                mock_stdout.read.return_value = b""

            mock_stdout.channel.recv_exit_status.return_value = 0
            mock_stderr = Mock()
            mock_stderr.read.return_value = b""
            return (None, mock_stdout, mock_stderr)

        mock_ssh.exec_command.side_effect = exec_command_side_effect

        sync_manager._add_to_path_in_shell_rc(mock_ssh, '$HOME/.local/bin')

        # Verify .bashrc was created with PATH
        calls = [str(call) for call in mock_ssh.exec_command.call_args_list]
        assert any('.bashrc' in call and 'export PATH' in call for call in calls)

    def test_add_to_path_in_shell_rc_zshrc_preferred(self, sync_manager):
        """Test using .zshrc when it exists before .bashrc"""
        mock_ssh = Mock()

        # Mock .zshrc exists (checked second), .bashrc doesn't exist
        def exec_command_side_effect(cmd):
            mock_stdout = Mock()
            if 'test -f ~/.bashrc' in cmd:
                mock_stdout.read.return_value = b""  # .bashrc doesn't exist
            elif 'test -f ~/.zshrc' in cmd:
                mock_stdout.read.return_value = b"exists"  # .zshrc exists
            elif 'grep -q' in cmd:
                mock_stdout.read.return_value = b""  # PATH not found
            else:
                mock_stdout.read.return_value = b""

            mock_stdout.channel.recv_exit_status.return_value = 0
            mock_stderr = Mock()
            mock_stderr.read.return_value = b""
            return (None, mock_stdout, mock_stderr)

        mock_ssh.exec_command.side_effect = exec_command_side_effect

        sync_manager._add_to_path_in_shell_rc(mock_ssh, '$HOME/.local/bin')

        # Verify PATH was added to .zshrc
        calls = [str(call) for call in mock_ssh.exec_command.call_args_list]
        assert any('.zshrc' in call and 'export PATH' in call for call in calls)
