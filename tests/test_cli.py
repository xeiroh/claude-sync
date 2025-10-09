"""
Tests for CLI argument parsing and command handling
"""

import pytest
from claude_sync.cli import create_parser, parse_ssh_command


class TestCLI:
    """Test CLI argument parsing"""

    @pytest.fixture
    def parser(self):
        """Create argument parser"""
        return create_parser()

    def test_help_flag(self, parser):
        """Test --help flag"""
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(['--help'])
        assert exc.value.code == 0

    def test_init_flag_alone(self, parser):
        """Test that --init works without target"""
        args = parser.parse_args(['--init'])

        assert args.init is True
        assert args.ssh is None
        assert args.server is None

    def test_list_profiles_alone(self, parser):
        """Test that --list-profiles works without target"""
        args = parser.parse_args(['--list-profiles'])

        assert args.list_profiles is True
        assert args.ssh is None
        assert args.server is None

    def test_ssh_target_basic(self, parser):
        """Test --ssh with basic target"""
        args = parser.parse_args(['--ssh', 'user@host'])

        assert args.ssh == 'user@host'
        assert args.server is None

    def test_ssh_with_profile(self, parser):
        """Test --ssh with --profile"""
        args = parser.parse_args(['--ssh', 'user@host', '--profile', 'generic-ubuntu'])

        assert args.ssh == 'user@host'
        assert args.profile == 'generic-ubuntu'

    def test_ssh_with_dry_run(self, parser):
        """Test --ssh with --dry-run"""
        args = parser.parse_args(['--ssh', 'user@host', '--dry-run'])

        assert args.ssh == 'user@host'
        assert args.dry_run is True

    def test_ssh_with_verbose(self, parser):
        """Test --ssh with --verbose"""
        args = parser.parse_args(['--ssh', 'user@host', '--verbose'])

        assert args.ssh == 'user@host'
        assert args.verbose is True

    def test_ssh_with_verbose_short(self, parser):
        """Test --ssh with -v (short form)"""
        args = parser.parse_args(['--ssh', 'user@host', '-v'])

        assert args.ssh == 'user@host'
        assert args.verbose is True

    def test_ssh_with_save_server(self, parser):
        """Test --ssh with --save-server"""
        args = parser.parse_args(['--ssh', 'user@host', '--save-server', 'myserver'])

        assert args.ssh == 'user@host'
        assert args.save_server == 'myserver'

    def test_server_target(self, parser):
        """Test --server with saved server name"""
        args = parser.parse_args(['--server', 'myserver'])

        assert args.server == 'myserver'
        assert args.ssh is None

    def test_ssh_and_server_mutually_exclusive(self, parser):
        """Test that --ssh and --server cannot be used together"""
        with pytest.raises(SystemExit):
            parser.parse_args(['--ssh', 'user@host', '--server', 'myserver'])

    def test_local_profile_flag(self, parser):
        """Test --local-profile flag"""
        args = parser.parse_args(['--ssh', 'user@host', '--local-profile', 'local-mac'])

        assert args.local_profile == 'local-mac'

    def test_interactive_flag(self, parser):
        """Test --interactive flag"""
        args = parser.parse_args(['--ssh', 'user@host', '--interactive'])

        assert args.interactive is True

    def test_all_flags_together(self, parser):
        """Test combining multiple flags"""
        args = parser.parse_args([
            '--ssh', 'user@host:2222',
            '--profile', 'aws-ubuntu',
            '--local-profile', 'local-mac',
            '--dry-run',
            '--verbose',
            '--save-server', 'aws-prod'
        ])

        assert args.ssh == 'user@host:2222'
        assert args.profile == 'aws-ubuntu'
        assert args.local_profile == 'local-mac'
        assert args.dry_run is True
        assert args.verbose is True
        assert args.save_server == 'aws-prod'

    def test_default_values(self, parser):
        """Test default values when flags not provided"""
        args = parser.parse_args(['--ssh', 'user@host'])

        assert args.profile is None
        assert args.local_profile is None
        assert args.dry_run is False
        assert args.verbose is False
        assert args.interactive is False
        assert args.save_server is None
        assert args.init is False
        assert args.list_profiles is False

    def test_no_arguments_fails(self, parser):
        """Test that providing no arguments shows error"""
        # Parser allows no args (for --init, --list-profiles)
        # but main() should validate
        args = parser.parse_args([])

        # Should parse but have no targets
        assert args.ssh is None
        assert args.server is None
        assert args.init is False
        assert args.list_profiles is False

    def test_key_argument_long(self, parser):
        """Test --key with SSH target"""
        args = parser.parse_args(['--ssh', 'user@host', '--key', '~/.ssh/my_key'])

        assert args.ssh == 'user@host'
        assert args.key == '~/.ssh/my_key'

    def test_key_argument_short(self, parser):
        """Test -i (short form of --key)"""
        args = parser.parse_args(['--ssh', 'user@host', '-i', '~/.ssh/my_key'])

        assert args.ssh == 'user@host'
        assert args.key == '~/.ssh/my_key'

    def test_ssh_command_basic(self, parser):
        """Test --ssh-command with basic SSH command"""
        args = parser.parse_args(['--ssh-command', 'ssh user@host'])

        assert args.ssh_command == 'ssh user@host'
        assert args.ssh is None

    def test_ssh_command_with_key(self, parser):
        """Test --ssh-command with -i flag"""
        args = parser.parse_args(['--ssh-command', 'ssh -i ~/.ssh/key user@host'])

        assert args.ssh_command == 'ssh -i ~/.ssh/key user@host'

    def test_ssh_command_with_port(self, parser):
        """Test --ssh-command with -p flag"""
        args = parser.parse_args(['--ssh-command', 'ssh -p 2222 user@host'])

        assert args.ssh_command == 'ssh -p 2222 user@host'

    def test_ssh_command_complex(self, parser):
        """Test --ssh-command with multiple flags"""
        args = parser.parse_args(['--ssh-command', 'ssh -i ~/.ssh/key -p 2222 user@host'])

        assert args.ssh_command == 'ssh -i ~/.ssh/key -p 2222 user@host'

    def test_ssh_and_ssh_command_mutually_exclusive(self, parser):
        """Test that --ssh and --ssh-command cannot be used together"""
        with pytest.raises(SystemExit):
            parser.parse_args(['--ssh', 'user@host', '--ssh-command', 'ssh user@host'])


class TestSSHCommandParsing:
    """Test SSH command parsing"""

    def test_basic_ssh_command(self):
        """Test parsing basic SSH command"""
        target, key = parse_ssh_command('ssh user@host')

        assert target == 'user@host'
        assert key is None

    def test_ssh_command_with_key_separate(self):
        """Test parsing SSH command with -i flag (separate)"""
        target, key = parse_ssh_command('ssh -i ~/.ssh/my_key user@host')

        assert target == 'user@host'
        assert key == '~/.ssh/my_key'

    def test_ssh_command_with_key_combined(self):
        """Test parsing SSH command with -i flag (combined)"""
        target, key = parse_ssh_command('ssh -i~/.ssh/my_key user@host')

        assert target == 'user@host'
        assert key == '~/.ssh/my_key'

    def test_ssh_command_with_identity_long(self):
        """Test parsing SSH command with --identity flag"""
        target, key = parse_ssh_command('ssh --identity ~/.ssh/my_key user@host')

        assert target == 'user@host'
        assert key == '~/.ssh/my_key'

    def test_ssh_command_with_port_separate(self):
        """Test parsing SSH command with -p flag (separate)"""
        target, key = parse_ssh_command('ssh -p 2222 user@host')

        assert target == 'user@host:2222'
        assert key is None

    def test_ssh_command_with_port_long(self):
        """Test parsing SSH command with --port flag"""
        target, key = parse_ssh_command('ssh --port 2222 user@host')

        assert target == 'user@host:2222'
        assert key is None

    def test_ssh_command_complex(self):
        """Test parsing complex SSH command"""
        target, key = parse_ssh_command('ssh -i ~/.ssh/key -p 3000 user@example.com')

        assert target == 'user@example.com:3000'
        assert key == '~/.ssh/key'

    def test_ssh_command_without_ssh_prefix(self):
        """Test parsing command without 'ssh' prefix"""
        target, key = parse_ssh_command('-i ~/.ssh/key user@host')

        assert target == 'user@host'
        assert key == '~/.ssh/key'

    def test_ssh_command_with_extra_flags(self):
        """Test parsing SSH command with unknown flags (should skip)"""
        target, key = parse_ssh_command('ssh -v -i ~/.ssh/key user@host')

        assert target == 'user@host'
        assert key == '~/.ssh/key'

    def test_ssh_command_no_target_raises(self):
        """Test that command without target raises error"""
        with pytest.raises(ValueError, match="Could not extract SSH target"):
            parse_ssh_command('ssh -i ~/.ssh/key')
