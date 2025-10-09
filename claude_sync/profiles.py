"""
Profile management for remote server configurations
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class ServerProfile:
    """Represents a server environment profile"""
    name: str
    home: str
    workspace: str
    npm_global: str
    install_method: str
    default_user: str
    persistent_storage: str
    platform: str
    note: Optional[str] = None


class ProfileManager:
    """Manages server profiles and auto-detection"""

    DEFAULT_PROFILES = {
        "vast-root": {
            "name": "Vast.ai (root user)",
            "home": "/root",
            "workspace": "/workspace",
            "npm_global": "/root/.npm-global",
            "install_method": "npm",
            "default_user": "root",
            "persistent_storage": "/workspace",
            "platform": "vast.ai"
        },
        "runpod-root": {
            "name": "RunPod (root user)",
            "home": "/root",
            "workspace": "/workspace",
            "npm_global": "/root/.npm-global",
            "install_method": "npm",
            "default_user": "root",
            "persistent_storage": "/workspace",
            "platform": "runpod"
        },
        "lambda-ubuntu": {
            "name": "Lambda Labs (ubuntu user)",
            "home": "/home/ubuntu",
            "workspace": "/home/ubuntu",
            "npm_global": "/home/ubuntu/.npm-global",
            "install_method": "npm",
            "default_user": "ubuntu",
            "persistent_storage": "/lambda/nfs",
            "platform": "lambda"
        },
        "paperspace-gradient": {
            "name": "Paperspace Gradient",
            "home": "/home/paperspace",
            "workspace": "/notebooks",
            "npm_global": "/home/paperspace/.npm-global",
            "install_method": "npm",
            "default_user": "paperspace",
            "persistent_storage": "/storage",
            "platform": "paperspace"
        },
        "aws-ubuntu": {
            "name": "AWS EC2 Ubuntu",
            "home": "/home/ubuntu",
            "workspace": "/home/ubuntu",
            "npm_global": "/home/ubuntu/.npm-global",
            "install_method": "npm",
            "default_user": "ubuntu",
            "persistent_storage": "/home/ubuntu",
            "platform": "aws-ec2"
        },
        "gcp-ubuntu": {
            "name": "Google Cloud Compute Engine",
            "home": "/home/{{ username }}",
            "workspace": "/home/{{ username }}",
            "npm_global": "/home/{{ username }}/.npm-global",
            "install_method": "npm",
            "default_user": "{{ username }}",
            "persistent_storage": "/home/{{ username }}",
            "platform": "gcp",
            "note": "Username is your Gmail account without @gmail.com"
        },
        "generic-ubuntu": {
            "name": "Generic Ubuntu Server",
            "home": "/home/{{ username }}",
            "workspace": "/home/{{ username }}/workspace",
            "npm_global": "/home/{{ username }}/.npm-global",
            "install_method": "npm",
            "default_user": "{{ username }}",
            "persistent_storage": "/home/{{ username }}",
            "platform": "ubuntu"
        },
        "generic-debian": {
            "name": "Generic Debian Server",
            "home": "/home/{{ username }}",
            "workspace": "/home/{{ username }}/workspace",
            "npm_global": "/home/{{ username }}/.npm-global",
            "install_method": "npm",
            "default_user": "{{ username }}",
            "persistent_storage": "/home/{{ username }}",
            "platform": "debian"
        },
        "local-mac": {
            "name": "Local macOS",
            "home": "/Users/{{ username }}",
            "workspace": "/Users/{{ username }}/Projects",
            "npm_global": "/Users/{{ username }}/.npm-global",
            "install_method": "native",
            "default_user": "{{ username }}",
            "persistent_storage": "/Users/{{ username }}",
            "platform": "macos"
        },
        "local-linux": {
            "name": "Local Linux",
            "home": "/home/{{ username }}",
            "workspace": "/home/{{ username }}/projects",
            "npm_global": "/home/{{ username }}/.npm-global",
            "install_method": "npm",
            "default_user": "{{ username }}",
            "persistent_storage": "/home/{{ username }}",
            "platform": "linux"
        },
        "local-windows": {
            "name": "Local Windows",
            "home": "C:/Users/{{ username }}",
            "workspace": "C:/Users/{{ username }}/Projects",
            "npm_global": "C:/Users/{{ username }}/AppData/Roaming/npm",
            "install_method": "native",
            "default_user": "{{ username }}",
            "persistent_storage": "C:/Users/{{ username }}",
            "platform": "windows"
        },
        "generic-windows": {
            "name": "Generic Windows Server",
            "home": "C:/Users/{{ username }}",
            "workspace": "C:/Users/{{ username }}/workspace",
            "npm_global": "C:/Users/{{ username }}/AppData/Roaming/npm",
            "install_method": "native",
            "default_user": "{{ username }}",
            "persistent_storage": "C:/Users/{{ username }}",
            "platform": "windows"
        }
    }

    def __init__(self):
        self.config_dir = Path.home() / ".claude-sync"
        self.profiles_file = self.config_dir / "profiles.json"
        self.servers_file = self.config_dir / "servers.json"

    def initialize_config(self) -> None:
        """Create config directory and default profiles file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        if not self.profiles_file.exists():
            with open(self.profiles_file, "w") as f:
                json.dump({"profiles": self.DEFAULT_PROFILES}, f, indent=2)

        if not self.servers_file.exists():
            with open(self.servers_file, "w") as f:
                json.dump({"servers": {}}, f, indent=2)

    def load_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Load profiles from config file"""
        if not self.profiles_file.exists():
            return self.DEFAULT_PROFILES

        with open(self.profiles_file, "r") as f:
            data = json.load(f)
            return data.get("profiles", {})

    def get_profile(self, name: str) -> Optional[ServerProfile]:
        """Get a specific profile by name"""
        profiles = self.load_profiles()
        if name not in profiles:
            return None

        profile_data = profiles[name]
        return ServerProfile(**profile_data)

    def detect_local_profile(self) -> str:
        """Detect local machine profile"""
        import platform

        system = platform.system()

        if system == "Darwin":
            return "local-mac"
        elif system == "Linux":
            return "local-linux"
        elif system == "Windows":
            return "local-windows"
        else:
            # Unknown system
            return "generic-ubuntu"  # fallback

    def detect_remote_profile(self, ssh_client) -> str:
        """
        Auto-detect remote platform profile
        Returns profile name that best matches the remote environment
        """
        # Platform-specific checks
        detection_checks = {
            'generic-windows': [
                'ver >nul 2>&1 && echo Windows'
            ],
            'vast-root': [
                'test -f /root/onstart.sh && test -d /workspace'
            ],
            'runpod-root': [
                'test -d /workspace && test -f /etc/runpod-release 2>/dev/null || test -d /workspace'
            ],
            'lambda-ubuntu': [
                'test -d /lambda/nfs && id -u ubuntu &>/dev/null'
            ],
            'paperspace-gradient': [
                'test -d /storage && test -d /notebooks && id -u paperspace &>/dev/null'
            ],
            'aws-ubuntu': [
                'test -f /sys/hypervisor/uuid && grep -q "ec2" /sys/hypervisor/uuid 2>/dev/null'
            ],
            'gcp-ubuntu': [
                'test -f /sys/class/dmi/id/product_name && grep -q "Google" /sys/class/dmi/id/product_name 2>/dev/null'
            ]
        }

        # Run checks in order of specificity
        for profile_name, checks in detection_checks.items():
            for check in checks:
                stdin, stdout, stderr = ssh_client.exec_command(check)
                exit_code = stdout.channel.recv_exit_status()

                if exit_code == 0:
                    return profile_name

        # Fallback: check if user is ubuntu or root
        stdin, stdout, stderr = ssh_client.exec_command('whoami')
        username = stdout.read().decode().strip()

        if username == 'ubuntu':
            return 'generic-ubuntu'
        elif username == 'root':
            # Could be vast or runpod, default to vast-root
            return 'vast-root'
        else:
            # Generic debian/ubuntu with custom user
            return 'generic-debian'

    def save_server_config(self, name: str, config: Dict[str, Any]) -> None:
        """Save a server configuration"""
        with open(self.servers_file, "r") as f:
            data = json.load(f)

        data["servers"][name] = config

        with open(self.servers_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_server_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Get saved server configuration"""
        if not self.servers_file.exists():
            return None

        with open(self.servers_file, "r") as f:
            data = json.load(f)
            return data.get("servers", {}).get(name)

    def template_profile(self, profile: ServerProfile, username: str) -> ServerProfile:
        """Replace {{ username }} placeholders in profile"""
        profile_dict = profile.__dict__.copy()

        for key, value in profile_dict.items():
            if isinstance(value, str) and "{{ username }}" in value:
                profile_dict[key] = value.replace("{{ username }}", username)

        return ServerProfile(**profile_dict)
