"""
Jinja2 templating for config file path translation
"""

import re
from typing import Any, Dict
from jinja2 import Template


class ConfigTemplater:
    """Handles templating of configuration files for remote environments"""

    def __init__(self, local_profile: Dict[str, str], remote_profile: Dict[str, str]):
        """
        Initialize with local and remote profiles

        Args:
            local_profile: Dictionary with local paths (home, workspace, etc.)
            remote_profile: Dictionary with remote paths (home, workspace, etc.)
        """
        self.local_profile = local_profile
        self.remote_profile = remote_profile
        self.path_mapping = self._build_path_mapping()

    def _build_path_mapping(self) -> Dict[str, str]:
        """Build path mapping from local to remote"""
        return {
            self.local_profile['home']: self.remote_profile['home'],
            self.local_profile['workspace']: self.remote_profile['workspace'],
            self.local_profile['npm_global']: self.remote_profile['npm_global'],
            self.local_profile['persistent_storage']: self.remote_profile['persistent_storage'],
        }

    def template_config(self, config: Any) -> Any:
        """
        Recursively template a configuration object

        Args:
            config: Configuration data (dict, list, str, etc.)

        Returns:
            Templated configuration with paths replaced
        """
        return self._template_recursive(config)

    def _template_recursive(self, obj: Any) -> Any:
        """Recursively process configuration objects"""
        if isinstance(obj, dict):
            return {k: self._template_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._template_recursive(item) for item in obj]
        elif isinstance(obj, str):
            return self._replace_paths(obj)
        else:
            return obj

    def _replace_paths(self, text: str) -> str:
        """
        Replace local paths with remote paths in a string

        Args:
            text: String potentially containing local paths

        Returns:
            String with local paths replaced by remote equivalents
        """
        result = text

        # Sort by length (descending) to replace longer paths first
        # This prevents partial replacements
        sorted_mappings = sorted(
            self.path_mapping.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )

        for local_path, remote_path in sorted_mappings:
            # Handle different path formats
            # 1. Direct paths: /Users/foo -> /home/bar
            result = result.replace(local_path, remote_path)

            # 2. File protocol paths: file:///Users/foo -> file:///home/bar
            result = result.replace(f"file://{local_path}", f"file://{remote_path}")

            # 3. Permission patterns: Read(//Users/foo/**) -> Read(//home/bar/**)
            result = result.replace(f"//{local_path}", f"//{remote_path}")

        return result

    def template_claude_json(self, claude_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Template ~/.claude.json file with path replacements

        Special handling:
        - Remove 'projects' object entirely
        - Template mcpServers paths
        - Keep OAuth and other settings
        """
        templated = self.template_config(claude_json)

        # Remove projects section (local project histories)
        if 'projects' in templated:
            del templated['projects']

        return templated

    def template_settings_json(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Template settings.json with permission path updates

        Args:
            settings: Settings configuration

        Returns:
            Settings with templated paths
        """
        return self.template_config(settings)

    def template_mcp_config(self, mcp_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Template MCP server configurations

        Handles:
        - Environment variables with paths
        - Command arguments with paths
        - Keeps API keys/tokens as-is
        """
        return self.template_config(mcp_config)

    def extract_local_paths(self, text: str) -> list[str]:
        """
        Extract potential local paths from text for analysis

        Returns:
            List of detected local paths
        """
        paths = []

        # Common local path patterns
        patterns = [
            r'/Users/[^\s:"\'\}]+',      # macOS paths
            r'/home/[^\s:"\'\}]+',        # Linux home paths
            r'C:\\[^\s:"\'\}]+',          # Windows paths
            r'/Applications/[^\s:"\'\}]+', # macOS applications
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            paths.extend(matches)

        return list(set(paths))  # Remove duplicates


def create_path_mapping(local_profile: Dict, remote_profile: Dict) -> Dict[str, str]:
    """
    Helper function to create path mapping from profiles

    Args:
        local_profile: Local server profile
        remote_profile: Remote server profile

    Returns:
        Dictionary mapping local paths to remote paths
    """
    return {
        local_profile.get('home', ''): remote_profile.get('home', ''),
        local_profile.get('workspace', ''): remote_profile.get('workspace', ''),
        local_profile.get('npm_global', ''): remote_profile.get('npm_global', ''),
        local_profile.get('persistent_storage', ''): remote_profile.get('persistent_storage', ''),
    }
