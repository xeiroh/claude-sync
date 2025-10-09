"""
Syncing and remote connection logic
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import paramiko

from claude_sync.profiles import ProfileManager, ServerProfile
from claude_sync.compatibility import CompatibilityChecker


class SyncManager:
    """Manages syncing Claude Code environment to remote machines"""

    def __init__(
        self,
        profile_manager: ProfileManager,
        local_profile: ServerProfile,
        dry_run: bool = False,
        verbose: bool = False
    ):
        self.profile_manager = profile_manager
        self.local_profile = local_profile
        self.dry_run = dry_run
        self.verbose = verbose

    def sync_to_ssh(
        self,
        ssh_target: str,
        remote_profile: Optional[str] = None,
        interactive: bool = False,
        key_file: Optional[str] = None
    ) -> None:
        """Sync via SSH connection"""
        if self.verbose:
            print(f"Connecting to {ssh_target}...")

        # Parse SSH target
        host, port, username = self._parse_ssh_target(ssh_target)

        # Establish SSH connection
        ssh_client = self._create_ssh_connection(host, port, username, key_file)

        try:
            # Detect or use specified remote profile
            if remote_profile:
                remote_profile_name = remote_profile
            else:
                remote_profile_name = self.profile_manager.detect_remote_profile(ssh_client)
                if self.verbose:
                    print(f"Detected remote profile: {remote_profile_name}")

            remote_profile_obj = self.profile_manager.get_profile(remote_profile_name)
            if not remote_profile_obj:
                raise ValueError(f"Profile '{remote_profile_name}' not found")

            # Get remote username
            stdin, stdout, stderr = ssh_client.exec_command('whoami')
            remote_username = stdout.read().decode().strip()

            # Template remote profile with actual username
            remote_profile_obj = self.profile_manager.template_profile(
                remote_profile_obj,
                remote_username
            )

            # Check if Claude Code is installed on remote, auto-install if needed
            is_installed, remote_version = self._check_remote_claude_installation(ssh_client)

            if not is_installed:
                # Get local version and install method
                local_version = self._get_local_claude_version()
                if not local_version:
                    raise ValueError(
                        "Could not detect local Claude Code version. "
                        "Ensure Claude Code is installed locally before syncing."
                    )

                # Get install method from local config
                home = Path.home()
                claude_json_path = home / ".claude.json"
                if not claude_json_path.exists():
                    raise ValueError(
                        "~/.claude.json not found. Ensure Claude Code is configured locally."
                    )

                with open(claude_json_path) as f:
                    local_config = json.load(f)
                    install_method = local_config.get('installMethod', 'npm')

                print(f"\nClaude Code not found on remote server")
                print(f"  Local version: {local_version} ({install_method})")
                print(f"  Auto-installing on remote...")

                # Install on remote
                success = self._install_claude_code_remote(
                    ssh_client,
                    install_method,
                    local_version,
                    remote_profile_obj.platform
                )

                if not success:
                    raise ValueError(
                        "Failed to install Claude Code on remote server. "
                        "Sync aborted. Please install manually and try again."
                    )
            else:
                if self.verbose:
                    print(f"Claude Code already installed on remote (version {remote_version})")

            # Initialize compatibility checker
            checker = CompatibilityChecker(
                local_profile=self.local_profile.__dict__,
                remote_profile=remote_profile_obj.__dict__
            )

            # Prepare configs
            configs = self._prepare_configs(checker)

            # Validate compatibility
            if not self._validate_compatibility(checker, configs):
                # Validation failed with critical errors
                print("\nSync aborted due to validation errors")
                return

            # Execute sync
            if not self.dry_run:
                self._execute_sync(ssh_client, remote_profile_obj, configs)
            else:
                self._print_sync_plan(remote_profile_obj, configs)

        finally:
            ssh_client.close()

    def sync_to_saved_server(self, server_config: Dict[str, Any]) -> None:
        """Sync to saved server configuration"""
        ssh_target = server_config['host']
        profile = server_config.get('profile')
        key_file = server_config.get('key')

        self.sync_to_ssh(
            ssh_target=ssh_target,
            remote_profile=profile if profile != 'auto-detect' else None,
            key_file=key_file
        )

    def _parse_ssh_target(self, ssh_target: str) -> tuple[str, int, str]:
        """
        Parse SSH target into components

        Formats supported:
        - user@host
        - user@host:port
        - host (uses current user)
        """
        port = 22
        username = os.getenv('USER')

        # Check for port
        if ':' in ssh_target:
            target, port_str = ssh_target.rsplit(':', 1)
            port = int(port_str)
            ssh_target = target

        # Check for username
        if '@' in ssh_target:
            username, host = ssh_target.split('@', 1)
        else:
            host = ssh_target

        return host, port, username

    def _get_local_claude_version(self) -> Optional[str]:
        """
        Get local Claude Code version

        Returns:
            Version string (e.g., "2.0.5") or None if not found
        """
        import platform

        # Try both 'claude' and 'claude-code' commands
        commands_to_try = ['claude', 'claude-code']

        # On Windows, also try explicit .exe paths in common locations
        if platform.system() == 'Windows':
            windows_paths = [
                Path.home() / 'AppData' / 'Local' / 'Programs' / 'Claude' / 'claude.exe',
                Path.home() / 'AppData' / 'Roaming' / 'npm' / 'claude.cmd',
                Path.home() / 'AppData' / 'Roaming' / 'npm' / 'claude-code.cmd',
            ]
            commands_to_try.extend([str(p) for p in windows_paths if p.exists()])

        for command in commands_to_try:
            try:
                result = subprocess.run(
                    [command, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    # Extract version from output
                    # Formats: "2.0.10 (Claude Code)", "claude-code 2.0.5", or just "2.0.5"
                    version = result.stdout.strip()
                    # Try to extract just the version number
                    parts = version.split()
                    for part in parts:
                        if part and part[0].isdigit():
                            return part
                    return version
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                continue

        return None

    def _check_remote_claude_installation(
        self,
        ssh_client: paramiko.SSHClient
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if Claude Code is installed on remote

        Returns:
            (is_installed, version)
        """
        # Try both 'claude' and 'claude-code' commands
        for command in ['claude', 'claude-code']:
            stdin, stdout, stderr = ssh_client.exec_command(f'{command} --version 2>&1')
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()

            # Check for command not found (Unix) or not recognized (Windows)
            not_found_indicators = ['command not found', 'not recognized', 'not found']
            if any(indicator in output.lower() or indicator in error.lower() for indicator in not_found_indicators):
                continue  # Try next command

            if output:
                # Extract version from output
                # Formats: "2.0.10 (Claude Code)", "claude-code 2.0.5", or just "2.0.5"
                parts = output.split()
                for part in parts:
                    if part and part[0].isdigit():
                        return True, part
                return True, output

        return False, None

    def _install_claude_code_remote(
        self,
        ssh_client: paramiko.SSHClient,
        install_method: str,
        version: str,
        platform: str = "linux"
    ) -> bool:
        """
        Install Claude Code on remote server

        Args:
            ssh_client: SSH connection to remote
            install_method: "npm", "npm-global", or "native"
            version: Version to install (e.g., "2.0.5")
            platform: Remote platform ("linux", "macos", "windows", etc.)

        Returns:
            True if installation succeeded, False otherwise
        """
        if self.verbose:
            print(f"\nInstalling Claude Code on remote server...")
            print(f"  Method: {install_method}")
            print(f"  Version: {version}")
            print(f"  Platform: {platform}")

        # Determine installation command based on method and platform
        if install_method in ['npm', 'npm-global']:
            cmd = f'npm install -g @anthropic-ai/claude-code@{version}'
        elif install_method == 'native':
            # Platform-specific native installation
            if platform == 'windows':
                # PowerShell installation (preferred for Windows)
                cmd = f'powershell -Command "& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) {version}"'
            else:
                # Unix-like systems (Linux, macOS)
                cmd = f'curl -fsSL https://claude.ai/install.sh | bash -s {version}'
        else:
            print(f"ERROR: Unknown install method: {install_method}")
            return False

        if self.verbose:
            print(f"  Running: {cmd}")

        # Execute installation
        stdin, stdout, stderr = ssh_client.exec_command(cmd)

        # Stream output if verbose
        if self.verbose:
            print("\n  Installation output:")
            for line in stdout:
                print(f"    {line.rstrip()}")

        # Check for errors
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error_output = stderr.read().decode().strip()
            print(f"\nERROR: Installation failed with exit code {exit_status}")
            if error_output:
                print(f"  {error_output}")
            return False

        # Verify installation
        is_installed, installed_version = self._check_remote_claude_installation(ssh_client)
        if is_installed:
            if self.verbose:
                print(f"\nSUCCESS: Claude Code installed successfully (version {installed_version})")
            return True
        else:
            print("\nERROR: Installation completed but Claude Code not found")
            return False

    def _create_ssh_connection(
        self,
        host: str,
        port: int,
        username: str,
        key_file: Optional[str] = None
    ) -> paramiko.SSHClient:
        """Create SSH connection with support for encrypted keys"""
        import getpass

        client = paramiko.SSHClient()

        # Warn about auto-accepting host keys
        print(f"Connecting to {host}:{port}...")
        print(f"Note: Host key will be automatically accepted if unknown")
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': host,
            'port': port,
            'username': username,
            'timeout': 10
        }

        def load_encrypted_key(key_path: Path) -> Optional[paramiko.PKey]:
            """Try to load an encrypted key with passphrase prompt"""
            passphrase = None
            key_obj = None

            # Try different key types
            for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
                try:
                    # Try loading without passphrase first
                    key_obj = key_class.from_private_key_file(str(key_path))
                    return key_obj
                except paramiko.PasswordRequiredException:
                    # Key is encrypted, prompt for password
                    if passphrase is None:
                        passphrase = getpass.getpass(f"Enter passphrase for {key_path}: ")
                    try:
                        key_obj = key_class.from_private_key_file(str(key_path), password=passphrase)
                        return key_obj
                    except paramiko.SSHException:
                        # Wrong passphrase or not this key type, try next type
                        continue
                except paramiko.SSHException:
                    # Not this key type, try next
                    continue

            return None

        # Add key file if specified
        if key_file:
            key_path = Path(key_file).expanduser()
            if not key_path.exists():
                raise FileNotFoundError(f"SSH key not found: {key_file}")

            key_obj = load_encrypted_key(key_path)
            if key_obj:
                connect_kwargs['pkey'] = key_obj
            else:
                # Fallback to key_filename (paramiko will handle it)
                connect_kwargs['key_filename'] = str(key_path)

        # Try to connect
        try:
            client.connect(**connect_kwargs)
        except paramiko.SSHException as e:
            # Check if error is due to encrypted private key in default locations
            if 'private key file is encrypted' in str(e).lower():
                # Try default key locations
                default_keys = [
                    Path.home() / '.ssh' / 'id_rsa',
                    Path.home() / '.ssh' / 'id_ed25519',
                    Path.home() / '.ssh' / 'id_ecdsa',
                    Path.home() / '.ssh' / 'id_dsa',
                ]

                loaded_key = None
                for default_key in default_keys:
                    if default_key.exists():
                        if self.verbose:
                            print(f"Trying key: {default_key}")
                        loaded_key = load_encrypted_key(default_key)
                        if loaded_key:
                            # Retry connection with loaded key
                            try:
                                connect_kwargs['pkey'] = loaded_key
                                client.connect(**connect_kwargs)
                                return client
                            except paramiko.AuthenticationException:
                                # This key didn't work, try next
                                continue

                # If we get here, no encrypted key worked
                raise ConnectionError(f"Failed to authenticate with encrypted keys for {username}@{host}:{port}")

            raise ConnectionError(f"Failed to connect to {username}@{host}:{port}: {e}")
        except paramiko.AuthenticationException as e:
            # If we have a key file but authentication failed, might be wrong passphrase
            if key_file and 'passphrase' in str(e).lower():
                raise ConnectionError(f"Authentication failed. Incorrect passphrase for key: {key_file}")
            raise ConnectionError(f"Authentication failed for {username}@{host}:{port}: {e}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {username}@{host}:{port}: {e}")

        return client

    def _validate_compatibility(
        self,
        checker: CompatibilityChecker,
        configs: Dict[str, Any]
    ) -> bool:
        """
        Validate compatibility between local and remote environments

        Returns:
            True if validation passes or user accepts warnings
            False if critical errors found
        """
        warnings = []
        errors = []

        # Check install method compatibility
        # Get installMethod from local ~/.claude.json (camelCase)
        local_install_method = None
        if 'claude_json' in configs:
            local_install_method = configs['claude_json'].get('installMethod')

        # Get install_method from remote profile (snake_case)
        remote_install_method = checker.remote_profile.get('install_method')

        if local_install_method and remote_install_method:
            if not checker.check_install_method(local_install_method, remote_install_method):
                warnings.append(
                    f"Install method mismatch: local ~/.claude.json has installMethod='{local_install_method}', "
                    f"but remote profile expects install_method='{remote_install_method}'"
                )
                warnings.append(
                    "  Claude Code may not work correctly on the remote server"
                )
                warnings.append(
                    f"  Consider reinstalling Claude Code on remote with: {remote_install_method}"
                )

        # Validate MCP servers in config
        if 'claude_json' in configs:
            claude_config = configs['claude_json']
            if 'mcpServers' in claude_config:
                mcp_servers = claude_config['mcpServers']

                for mcp_name, mcp_config in mcp_servers.items():
                    is_compatible, issues = checker.validate_mcp_server(mcp_name, mcp_config)

                    if not is_compatible:
                        warnings.append(f"MCP server '{mcp_name}' may have compatibility issues:")
                        for issue in issues:
                            warnings.append(f"  - {issue}")

        # Print validation results
        if warnings or errors:
            print("\nCompatibility Validation Results:")
            print("=" * 50)

            if errors:
                print("\nCRITICAL ERRORS:")
                for error in errors:
                    print(f"  {error}")

            if warnings:
                print("\nWARNINGS:")
                for warning in warnings:
                    print(f"  {warning}")

            print("=" * 50)

            # If there are errors, abort
            if errors:
                print("\nSync aborted due to critical errors")
                return False

            # If only warnings, continue (user can ctrl-C if needed)
            if warnings and self.verbose:
                print("\nProceeding with warnings (press Ctrl-C to cancel)...")
                import time
                time.sleep(2)

        return True

    def _prepare_configs(self, checker: CompatibilityChecker) -> Dict[str, Any]:
        """Prepare all configs for syncing"""
        home = Path.home()
        configs = {}

        # Sanitize ~/.claude.json
        claude_json_path = home / ".claude.json"
        if claude_json_path.exists():
            configs['claude_json'] = checker.sanitize_claude_json(claude_json_path)

        # Sanitize ~/.claude/settings.json
        settings_path = home / ".claude" / "settings.json"
        if settings_path.exists():
            configs['settings_json'] = checker.sanitize_settings_json(settings_path)

        # Get sync plan for ~/.claude/ directory
        claude_dir = home / ".claude"
        files_to_sync, files_to_skip = checker.get_sync_plan(claude_dir)

        configs['files_to_sync'] = files_to_sync
        configs['files_to_skip'] = files_to_skip

        return configs

    def _execute_sync(
        self,
        ssh_client: paramiko.SSHClient,
        remote_profile: ServerProfile,
        configs: Dict[str, Any]
    ) -> None:
        """Execute the actual file sync"""
        sftp = ssh_client.open_sftp()

        try:
            # Create remote directories
            remote_home = remote_profile.home
            remote_claude_dir = f"{remote_home}/.claude"

            self._ensure_remote_dir(sftp, remote_home)
            self._ensure_remote_dir(sftp, remote_claude_dir)

            # Sync ~/.claude.json
            if 'claude_json' in configs:
                remote_path = f"{remote_home}/.claude.json"
                if self.verbose:
                    print(f"Syncing ~/.claude.json -> {remote_path}")

                with sftp.open(remote_path, 'w') as f:
                    json.dump(configs['claude_json'], f, indent=2)

            # Sync ~/.claude/settings.json
            if 'settings_json' in configs:
                remote_path = f"{remote_claude_dir}/settings.json"
                if self.verbose:
                    print(f"Syncing ~/.claude/settings.json -> {remote_path}")

                with sftp.open(remote_path, 'w') as f:
                    json.dump(configs['settings_json'], f, indent=2)

            # Sync other files
            for local_file in configs.get('files_to_sync', []):
                relative_path = local_file.relative_to(Path.home() / ".claude")
                remote_path = f"{remote_claude_dir}/{relative_path}"

                # Ensure remote directory exists
                remote_dir = os.path.dirname(remote_path)
                self._ensure_remote_dir(sftp, remote_dir)

                if local_file.is_file():
                    if self.verbose:
                        print(f"Syncing {local_file.name} -> {remote_path}")

                    # Use compatibility checker to process file
                    checker = CompatibilityChecker(
                        local_profile=self.local_profile.__dict__,
                        remote_profile=remote_profile.__dict__
                    )
                    content = checker.process_file_for_sync(local_file)

                    # Write to remote
                    if isinstance(content, dict):
                        with sftp.open(remote_path, 'w') as f:
                            json.dump(content, f, indent=2)
                    elif isinstance(content, str):
                        with sftp.open(remote_path, 'w') as f:
                            f.write(content)
                    else:
                        # Binary content
                        with sftp.open(remote_path, 'wb') as f:
                            f.write(content)

                elif local_file.is_dir():
                    # Recursively sync directory
                    self._sync_directory(sftp, local_file, remote_path, remote_profile)

            print("\n✓ Sync completed successfully")

        finally:
            sftp.close()

    def _sync_directory(
        self,
        sftp,
        local_dir: Path,
        remote_dir: str,
        remote_profile: ServerProfile
    ) -> None:
        """Recursively sync a directory"""
        self._ensure_remote_dir(sftp, remote_dir)

        checker = CompatibilityChecker(
            local_profile=self.local_profile.__dict__,
            remote_profile=remote_profile.__dict__
        )

        for item in local_dir.iterdir():
            if not checker.should_sync_item(item.name):
                continue

            remote_path = f"{remote_dir}/{item.name}"

            if item.is_file():
                content = checker.process_file_for_sync(item)

                if isinstance(content, dict):
                    with sftp.open(remote_path, 'w') as f:
                        json.dump(content, f, indent=2)
                elif isinstance(content, str):
                    with sftp.open(remote_path, 'w') as f:
                        f.write(content)
                else:
                    with sftp.open(remote_path, 'wb') as f:
                        f.write(content)

            elif item.is_dir():
                self._sync_directory(sftp, item, remote_path, remote_profile)

    def _ensure_remote_dir(self, sftp, remote_path: str) -> None:
        """Ensure remote directory exists"""
        try:
            sftp.stat(remote_path)
        except FileNotFoundError:
            # Create directory
            parts = remote_path.split('/')
            current_path = ''

            for part in parts:
                if not part:
                    continue

                current_path += f"/{part}"
                try:
                    sftp.stat(current_path)
                except FileNotFoundError:
                    sftp.mkdir(current_path)

    def _print_sync_plan(
        self,
        remote_profile: ServerProfile,
        configs: Dict[str, Any]
    ) -> None:
        """Print what would be synced (dry run)"""
        print(f"\n=== Sync Plan ===")
        print(f"Remote: {remote_profile.home}")
        print(f"Profile: {remote_profile.name}")
        print()

        print("Files to sync:")
        if 'claude_json' in configs:
            print(f"  ✓ ~/.claude.json")
        if 'settings_json' in configs:
            print(f"  ✓ ~/.claude/settings.json")

        for file in configs.get('files_to_sync', []):
            print(f"  ✓ ~/.claude/{file.name}")

        print("\nFiles to skip:")
        for file in configs.get('files_to_skip', []):
            print(f"  ✗ ~/.claude/{file.name}")

        print()
