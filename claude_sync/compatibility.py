"""
Compatibility checking and config sanitization
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Tuple

from claude_sync.templates import ConfigTemplater


class CompatibilityChecker:
    """Checks and sanitizes configs for remote compatibility"""

    # Files/directories to skip during sync
    SKIP_ITEMS = {
        'projects',      # Local project histories
        'todos',         # Session-specific todos
        'logs',          # Local logs
        'shell-snapshots',  # Local shell state
        'ide',           # IDE-specific state
        'statsig',       # Analytics
    }

    # Files/directories to always sync
    SYNC_ITEMS = {
        'agents',        # Custom agents
        'commands',      # Slash commands
        'settings.json', # Global settings
        'CLAUDE.md',     # Global instructions
    }

    def __init__(self, local_profile: Dict, remote_profile: Dict):
        self.local_profile = local_profile
        self.remote_profile = remote_profile
        self.templater = ConfigTemplater(local_profile, remote_profile)

    def sanitize_claude_json(self, claude_json_path: Path) -> Dict[str, Any]:
        """
        Sanitize ~/.claude.json for remote sync

        Steps:
        1. Load file
        2. Remove projects object
        3. Template all paths
        4. Keep API keys/tokens as-is

        Returns:
            Sanitized config ready for remote
        """
        with open(claude_json_path, 'r') as f:
            config = json.load(f)

        # Remove local project references
        if 'projects' in config:
            del config['projects']

        # Template paths using Jinja2
        config = self.templater.template_claude_json(config)

        return config

    def sanitize_settings_json(self, settings_path: Path) -> Dict[str, Any]:
        """
        Sanitize settings.json with path templating

        Handles:
        - Permission rules with paths
        - Any other path references
        """
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        # Template all paths
        settings = self.templater.template_settings_json(settings)

        return settings

    def should_sync_item(self, item_name: str) -> bool:
        """
        Check if an item in ~/.claude/ should be synced

        Args:
            item_name: Name of file or directory

        Returns:
            True if item should be synced
        """
        # Explicitly skip certain items
        if item_name in self.SKIP_ITEMS:
            return False

        # Skip hidden files except settings
        if item_name.startswith('.') and item_name not in {'settings.json', 'settings.local.json'}:
            return False

        # Skip JSON files that aren't settings
        if item_name.endswith('.json') and 'settings' not in item_name:
            # Check if it's a metadata file
            if 'metadata' in item_name:
                return False

        # Skip JSONL files (chat histories)
        if item_name.endswith('.jsonl'):
            return False

        # Sync markdown files (framework docs, modes, etc.)
        if item_name.endswith('.md'):
            return True

        # Sync agents and commands directories
        if item_name in self.SYNC_ITEMS:
            return True

        return True  # Default: sync

    def get_sync_plan(self, claude_dir: Path) -> Tuple[List[Path], List[Path]]:
        """
        Analyze ~/.claude/ and determine what to sync

        Returns:
            (files_to_sync, files_to_skip)
        """
        files_to_sync = []
        files_to_skip = []

        if not claude_dir.exists():
            return files_to_sync, files_to_skip

        for item in claude_dir.iterdir():
            if self.should_sync_item(item.name):
                files_to_sync.append(item)
            else:
                files_to_skip.append(item)

        return files_to_sync, files_to_skip

    def process_file_for_sync(self, file_path: Path) -> Any:
        """
        Process a file for syncing (apply templating if needed)

        Args:
            file_path: Path to file

        Returns:
            Processed file content
        """
        # JSON files need templating
        if file_path.suffix == '.json':
            with open(file_path, 'r') as f:
                data = json.load(f)
            return self.templater.template_config(data)

        # Markdown files might have paths in code blocks
        elif file_path.suffix == '.md':
            with open(file_path, 'r') as f:
                content = f.read()
            return self.templater._replace_paths(content)

        # Other files: read as-is
        else:
            with open(file_path, 'rb') as f:
                return f.read()

    def validate_mcp_server(self, mcp_name: str, mcp_config: Dict) -> Tuple[bool, List[str]]:
        """
        Validate if MCP server config will work on remote

        Returns:
            (is_compatible, list_of_issues)
        """
        issues = []

        # Check command exists
        if 'command' in mcp_config:
            command = mcp_config['command']
            # Common commands that should be available
            common_commands = ['npx', 'uvx', 'docker', 'node', 'python']
            if command not in common_commands:
                # Check for absolute paths
                if command.startswith('/'):
                    issues.append(f"Command uses absolute path: {command}")

        # Check args for local paths
        if 'args' in mcp_config:
            args = mcp_config['args']
            if isinstance(args, list):
                for arg in args:
                    if isinstance(arg, str):
                        local_paths = self.templater.extract_local_paths(arg)
                        if local_paths:
                            issues.append(f"Arg contains local path: {arg}")

        # Check env vars for local paths
        if 'env' in mcp_config:
            env = mcp_config['env']
            for key, value in env.items():
                if isinstance(value, str):
                    local_paths = self.templater.extract_local_paths(value)
                    if local_paths:
                        # These are OK - will be templated
                        pass

        is_compatible = len(issues) == 0
        return is_compatible, issues

    def check_install_method(self, local_method: str, remote_method: str) -> bool:
        """
        Check if install methods are compatible

        Returns:
            True if compatible
        """
        # Same method: always compatible
        if local_method == remote_method:
            return True

        # npm and native are usually compatible
        if {local_method, remote_method} <= {'npm', 'native'}:
            return True

        # Different package managers: might have issues
        return False
