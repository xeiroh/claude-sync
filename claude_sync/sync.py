"""
Syncing and remote connection logic
"""

import json
import os
import re
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

                # Install on remote (continues even if verification fails)
                self._install_claude_code_remote(
                    ssh_client,
                    install_method,
                    local_version,
                    remote_profile_obj.platform,
                    remote_profile_obj.home
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

    def _extract_version_from_text(self, text: str) -> Optional[str]:
        """Extract semantic version string from arbitrary CLI output"""
        if not text:
            return None

        match = re.search(r"(\d+\.\d+\.\d+)", text)
        if match:
            return match.group(1)

        return None

    def _get_local_claude_version(self) -> Optional[str]:
        """
        Get local Claude Code version

        Returns:
            Version string (e.g., "2.0.5") or None if not found
        """
        import platform

        home = Path.home()
        system = platform.system()

        # Try both 'claude' and 'claude-code' commands first
        commands_to_try: list[str] = ['claude', 'claude-code']

        # Build additional PATH entries to help subprocess find the binary
        extra_paths: list[str] = []
        if getattr(self.local_profile, 'npm_global', None):
            npm_global_path = Path(self.local_profile.npm_global)
            extra_paths.append(str(npm_global_path / 'bin'))
            extra_paths.append(str(npm_global_path))

        # Common user-level install locations
        extra_paths.extend([
            str(home / '.npm-global' / 'bin'),
            str(home / '.local' / 'bin'),
        ])

        # Windows-specific paths and direct executables
        if system == 'Windows':
            windows_roaming = home / 'AppData' / 'Roaming'
            windows_local = home / 'AppData' / 'Local' / 'Programs'
            extra_paths.append(str(windows_roaming / 'npm'))
            extra_paths.append(str(windows_local / 'Claude'))

            commands_to_try.extend([
                str(windows_local / 'Claude' / 'claude.exe'),
                str(windows_roaming / 'npm' / 'claude.cmd'),
                str(windows_roaming / 'npm' / 'claude-code.cmd'),
                str(windows_roaming / 'npm' / 'claude.exe'),
                str(windows_roaming / 'npm' / 'claude-code.exe'),
            ])

        # Extend direct command attempts with discovered directories
        binary_names = ['claude', 'claude-code', 'claude.cmd', 'claude-code.cmd', 'claude.exe', 'claude-code.exe']
        for path_str in extra_paths:
            if not path_str:
                continue
            bin_path = Path(path_str)
            for binary in binary_names:
                commands_to_try.append(str(bin_path / binary))

        # Ensure we only try each command once (preserve order)
        seen_commands = set()
        ordered_commands = []
        for cmd in commands_to_try:
            if cmd and cmd not in seen_commands:
                seen_commands.add(cmd)
                ordered_commands.append(cmd)

        # Prepare environment with the augmented PATH
        env = os.environ.copy()
        existing_path = env.get('PATH', '')
        augmented_paths = [p for p in extra_paths if p]
        if existing_path:
            augmented_paths.append(existing_path)
        env['PATH'] = os.pathsep.join(augmented_paths) if augmented_paths else existing_path

        for command in ordered_commands:
            try:
                result = subprocess.run(
                    [command, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env
                )
                if result.returncode == 0:
                    # Extract version from output
                    # Formats: "2.0.10 (Claude Code)", "claude-code 2.0.5", or just "2.0.5"
                    stdout = (result.stdout or '').strip()
                    stderr = (result.stderr or '').strip()

                    # Some installations print version information to stderr
                    combined_output = stdout or stderr

                    # Skip common "not found" indicators even if exit code is zero
                    lower_combined = combined_output.lower()
                    if any(ind in lower_combined for ind in ['command not found', 'not recognized', 'no such file']):
                        continue

                    if combined_output:
                        version = self._extract_version_from_text(combined_output)
                        if version:
                            return version
                        return combined_output
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
            output = stdout.read().decode(errors='ignore').strip()
            error = stderr.read().decode(errors='ignore').strip()

            combined_output = output or error
            combined_for_check = f"{output} {error}".strip()

            # Check for command not found (Unix) or not recognized (Windows)
            not_found_indicators = ['command not found', 'not recognized', 'not found']
            if any(indicator in combined_for_check.lower() for indicator in not_found_indicators):
                continue  # Try next command

            if combined_output:
                # Extract version from output (stdout may be empty if CLI prints to stderr)
                version = self._extract_version_from_text(combined_output)
                if version:
                    return True, version
                return True, combined_output

        return False, None

    def _add_to_path_in_shell_rc(
        self,
        ssh_client: paramiko.SSHClient,
        path_to_add: str
    ) -> Optional[str]:
        """
        Add directory to PATH in shell RC files if not already present
        and source the RC file to make it immediately available

        Args:
            ssh_client: SSH connection to remote
            path_to_add: Directory path to add to PATH (e.g., ~/.local/bin)

        Returns:
            Path to the RC file that was modified, or None if no modification needed
        """
        # Detect which shell RC file to use (in order of preference)
        rc_files = ['.bashrc', '.zshrc', '.profile', '.bash_profile']
        modified_rc = None

        for rc_file in rc_files:
            # Check if RC file exists
            check_cmd = f'test -f ~/{rc_file} && echo "exists"'
            stdin, stdout, stderr = ssh_client.exec_command(check_cmd)
            output = stdout.read().decode().strip()

            if output == 'exists':
                # Check if PATH entry already exists
                check_path_cmd = f'grep -q "export PATH.*{path_to_add}" ~/{rc_file} && echo "found"'
                stdin, stdout, stderr = ssh_client.exec_command(check_path_cmd)
                path_exists = stdout.read().decode().strip()

                if path_exists != 'found':
                    # Add PATH entry
                    path_line = f'export PATH="{path_to_add}:$PATH"'
                    add_cmd = f'echo \'\n# Added by claude-sync\n{path_line}\' >> ~/{rc_file}'
                    stdin, stdout, stderr = ssh_client.exec_command(add_cmd)
                    stdout.channel.recv_exit_status()  # Wait for completion

                    if self.verbose:
                        print(f"  Added {path_to_add} to PATH in ~/{rc_file}")
                    
                    modified_rc = rc_file
                else:
                    if self.verbose:
                        print(f"  PATH already contains {path_to_add} in ~/{rc_file}")

                # Source the RC file to make PATH available immediately
                source_cmd = f'source ~/{rc_file} 2>/dev/null || . ~/{rc_file} 2>/dev/null'
                stdin, stdout, stderr = ssh_client.exec_command(source_cmd)
                stdout.channel.recv_exit_status()

                if self.verbose and modified_rc:
                    print(f"  Sourced ~/{rc_file} to activate PATH immediately")

                # Only update the first RC file found
                return rc_file

        # If no RC file exists, create .bashrc
        if self.verbose:
            print(f"  No RC file found, creating ~/.bashrc")
        path_line = f'export PATH="{path_to_add}:$PATH"'
        create_cmd = f'echo \'# Added by claude-sync\n{path_line}\' > ~/.bashrc'
        stdin, stdout, stderr = ssh_client.exec_command(create_cmd)
        stdout.channel.recv_exit_status()

        # Source the newly created .bashrc
        source_cmd = 'source ~/.bashrc 2>/dev/null || . ~/.bashrc 2>/dev/null'
        stdin, stdout, stderr = ssh_client.exec_command(source_cmd)
        stdout.channel.recv_exit_status()

        if self.verbose:
            print(f"  Sourced ~/.bashrc to activate PATH immediately")

        return '.bashrc'

    def _install_claude_code_remote(
        self,
        ssh_client: paramiko.SSHClient,
        install_method: str,
        version: str,
        platform: str = "linux",
        remote_home: str = "/root"
    ) -> bool:
        """
        Install Claude Code on remote server

        Args:
            ssh_client: SSH connection to remote
            install_method: "npm", "npm-global", or "native"
            version: Version to install (e.g., "2.0.5")
            platform: Remote platform ("linux", "macos", "windows", etc.)
            remote_home: Remote home directory path

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
            print(f"\nWARNING: Installation command exited with code {exit_status}")
            if error_output:
                print(f"  {error_output}")
            print("  Continuing with sync...")
            return True  # Don't abort, continue with sync

        # Determine installation path for verification (use actual paths, not $HOME)
        install_path = None
        install_path_display = None  # For RC file PATH entry
        if platform != 'windows':
            if install_method == 'native':
                install_path = f'{remote_home}/.local/bin'
                install_path_display = '$HOME/.local/bin'
            elif install_method in ['npm', 'npm-global']:
                # Get npm global bin directory
                stdin, stdout, stderr = ssh_client.exec_command('npm bin -g 2>/dev/null')
                npm_bin = stdout.read().decode().strip()
                if npm_bin and 'command not found' not in npm_bin.lower():
                    install_path = npm_bin
                    install_path_display = npm_bin
                else:
                    install_path = f'{remote_home}/.npm-global/bin'
                    install_path_display = '$HOME/.npm-global/bin'

        # Add to PATH in shell RC files (Unix only) - use display version with $HOME
        if platform != 'windows' and install_path_display:
            if self.verbose:
                print("\n  Configuring PATH in shell RC files...")

            self._add_to_path_in_shell_rc(ssh_client, install_path_display)

        # Verify installation (non-blocking) - use actual path for verification
        if platform != 'windows' and install_path:
            if self.verbose:
                print(f"\n  Verifying installation in {install_path}...")
            
            # Simple direct check - just see if the file exists
            check_cmd = f'ls -la {install_path}/claude* 2>&1'
            stdin, stdout, stderr = ssh_client.exec_command(check_cmd)
            ls_output = stdout.read().decode().strip()
            
            if self.verbose:
                print(f"  Files in {install_path}:")
                print(f"    {ls_output if ls_output else 'No files found'}")
            
            # Try to get version from the binary directly
            check_cmd = f'{install_path}/claude --version 2>&1'
            stdin, stdout, stderr = ssh_client.exec_command(check_cmd)
            output = stdout.read().decode(errors='ignore').strip()
            error_output = stderr.read().decode(errors='ignore').strip()
            combined_version_output = output or error_output
            
            if self.verbose:
                display_output = combined_version_output if combined_version_output else '(empty)'
                print(f"  Version check output: {display_output}")

            combined_lower = (combined_version_output or '').lower()
            if combined_version_output and 'command not found' not in combined_lower and 'no such file' not in combined_lower:
                # Found it!
                version = self._extract_version_from_text(combined_version_output)
                if version:
                    if self.verbose:
                        print(f"\n✓ Claude Code installed successfully (version {version})")
                    return True

                # Got some output but no clear version number
                if self.verbose:
                    print(f"\n✓ Claude Code binary found at {install_path}/claude")
                return True

        # Fallback: standard verification (tries default PATH)
        if self.verbose:
            print("\n  Trying standard verification (default PATH)...")
        
        is_installed, installed_version = self._check_remote_claude_installation(ssh_client)
        if is_installed:
            if self.verbose:
                print(f"\n✓ Claude Code installed successfully (version {installed_version})")
            return True
        else:
            # Installation completed but verification failed - continue anyway
            if self.verbose:
                print("\nNote: Claude Code installation verification inconclusive")
                print(f"  Installation completed - binary should be at {install_path if install_path else 'installation directory'}")
                print("  Continuing with configuration sync...")
            return True  # Don't abort, continue with sync

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

    def _write_json_file_safe(
        self,
        sftp,
        content: Dict[str, Any],
        remote_path: str
    ) -> None:
        """
        Safely write JSON file to remote with validation
        
        Uses atomic write pattern: write to temp file, validate, then move
        """
        import tempfile
        
        # Serialize to JSON string first
        json_str = json.dumps(content, indent=2)
        
        # Write to temporary file on remote
        temp_path = f"{remote_path}.tmp"
        
        try:
            # Write JSON string to temp file
            with sftp.open(temp_path, 'w') as f:
                f.write(json_str)
                # Force flush and sync
                f.flush()
                if hasattr(f, 'prefetch'):
                    # Wait for write to complete
                    pass
            
            # Verify the temp file is valid JSON by reading it back
            with sftp.open(temp_path, 'r') as f:
                readback = f.read()
                try:
                    json.loads(readback)
                except json.JSONDecodeError as e:
                    raise ValueError(f"JSON validation failed after write: {e}")
            
            # Remove destination file if it exists (SFTP rename doesn't overwrite)
            try:
                sftp.remove(remote_path)
            except FileNotFoundError:
                pass  # File doesn't exist, that's fine
            
            # Atomic move to final location
            sftp.rename(temp_path, remote_path)
            
        except Exception as e:
            # Clean up temp file on error
            try:
                sftp.remove(temp_path)
            except:
                pass
            raise

    def _execute_sync(
        self,
        ssh_client: paramiko.SSHClient,
        remote_profile: ServerProfile,
        configs: Dict[str, Any]
    ) -> None:
        """Execute the actual file sync"""
        import sys
        
        sftp = ssh_client.open_sftp()

        try:
            # Create remote directories
            remote_home = remote_profile.home
            remote_claude_dir = f"{remote_home}/.claude"

            if self.verbose:
                print("Creating remote directories...")
                sys.stdout.flush()

            self._ensure_remote_dir(sftp, remote_home)
            self._ensure_remote_dir(sftp, remote_claude_dir)

            if self.verbose:
                print("  ✓ Directories created")
                sys.stdout.flush()

            # Sync ~/.claude.json using safe atomic write
            if 'claude_json' in configs:
                remote_path = f"{remote_home}/.claude.json"
                if self.verbose:
                    print(f"\nSyncing ~/.claude.json -> {remote_path}")
                    sys.stdout.flush()

                self._write_json_file_safe(sftp, configs['claude_json'], remote_path)
                
                if self.verbose:
                    print("  ✓ ~/.claude.json synced")
                    sys.stdout.flush()

            # Sync ~/.claude/settings.json using safe atomic write
            if 'settings_json' in configs:
                remote_path = f"{remote_claude_dir}/settings.json"
                if self.verbose:
                    print(f"\nSyncing ~/.claude/settings.json -> {remote_path}")
                    sys.stdout.flush()

                self._write_json_file_safe(sftp, configs['settings_json'], remote_path)
                
                if self.verbose:
                    print("  ✓ settings.json synced")
                    sys.stdout.flush()

            # Sync other files
            files_to_sync = configs.get('files_to_sync', [])
            if files_to_sync and self.verbose:
                print(f"\nSyncing {len(files_to_sync)} additional files...")
                sys.stdout.flush()

            for local_file in files_to_sync:
                relative_path = local_file.relative_to(Path.home() / ".claude")
                remote_path = f"{remote_claude_dir}/{relative_path}"

                # Ensure remote directory exists
                remote_dir = os.path.dirname(remote_path)
                self._ensure_remote_dir(sftp, remote_dir)

                if local_file.is_file():
                    if self.verbose:
                        print(f"  {local_file.name} -> {remote_path}")
                        sys.stdout.flush()

                    # Use compatibility checker to process file
                    checker = CompatibilityChecker(
                        local_profile=self.local_profile.__dict__,
                        remote_profile=remote_profile.__dict__
                    )
                    content = checker.process_file_for_sync(local_file)

                    # Write to remote - use safe write for JSON
                    if isinstance(content, dict):
                        self._write_json_file_safe(sftp, content, remote_path)
                    elif isinstance(content, str):
                        with sftp.open(remote_path, 'w') as f:
                            f.write(content)
                            f.flush()
                    else:
                        # Binary content
                        with sftp.open(remote_path, 'wb') as f:
                            f.write(content)
                            f.flush()

                elif local_file.is_dir():
                    if self.verbose:
                        print(f"  {local_file.name}/ (directory)")
                        sys.stdout.flush()
                    # Recursively sync directory
                    self._sync_directory(sftp, local_file, remote_path, remote_profile)

            print("\n✓ Sync completed successfully")
            sys.stdout.flush()

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
                    # Use safe atomic write for JSON
                    self._write_json_file_safe(sftp, content, remote_path)
                elif isinstance(content, str):
                    with sftp.open(remote_path, 'w') as f:
                        f.write(content)
                        f.flush()
                else:
                    with sftp.open(remote_path, 'wb') as f:
                        f.write(content)
                        f.flush()

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
