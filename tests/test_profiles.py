"""
Tests for profile management and detection
"""

import pytest
import tempfile
import json
from pathlib import Path
from claude_sync.profiles import ProfileManager, ServerProfile


class TestProfileManager:
    """Test profile loading, detection, and management"""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def profile_manager(self, temp_config_dir):
        """Create ProfileManager with temporary config directory"""
        manager = ProfileManager()
        manager.config_dir = temp_config_dir
        manager.profiles_file = temp_config_dir / "profiles.json"
        manager.servers_file = temp_config_dir / "servers.json"
        return manager

    def test_default_profiles_exist(self):
        """Test that all 10 default profiles are defined"""
        expected_profiles = [
            "vast-root",
            "runpod-root",
            "lambda-ubuntu",
            "paperspace-gradient",
            "aws-ubuntu",
            "gcp-ubuntu",
            "generic-ubuntu",
            "generic-debian",
            "local-mac",
            "local-linux"
        ]

        for profile_name in expected_profiles:
            assert profile_name in ProfileManager.DEFAULT_PROFILES

    def test_initialize_config_creates_directory(self, profile_manager):
        """Test that initialize_config creates config directory"""
        profile_manager.initialize_config()

        assert profile_manager.config_dir.exists()
        assert profile_manager.config_dir.is_dir()

    def test_initialize_config_creates_profiles_file(self, profile_manager):
        """Test that initialize_config creates profiles.json"""
        profile_manager.initialize_config()

        assert profile_manager.profiles_file.exists()

        # Verify content
        with open(profile_manager.profiles_file) as f:
            data = json.load(f)
            assert "profiles" in data
            assert len(data["profiles"]) == 12  # 10 original + 2 Windows profiles

    def test_load_profiles(self, profile_manager):
        """Test loading profiles from file"""
        profile_manager.initialize_config()
        profiles = profile_manager.load_profiles()

        assert isinstance(profiles, dict)
        assert len(profiles) == 12  # 10 original + 2 Windows profiles
        assert "vast-root" in profiles
        assert "local-mac" in profiles
        assert "local-windows" in profiles
        assert "generic-windows" in profiles

    def test_get_profile_returns_server_profile(self, profile_manager):
        """Test get_profile returns ServerProfile object"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("vast-root")

        assert isinstance(profile, ServerProfile)
        assert profile.name == "Vast.ai (root user)"
        assert profile.home == "/root"
        assert profile.workspace == "/workspace"
        assert profile.platform == "vast.ai"

    def test_get_profile_returns_none_for_invalid(self, profile_manager):
        """Test get_profile returns None for invalid profile name"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("nonexistent")

        assert profile is None

    def test_template_profile_replaces_username(self, profile_manager):
        """Test template_profile replaces {{ username }} placeholders"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("gcp-ubuntu")

        # Original has {{ username }} placeholders
        assert "{{ username }}" in profile.home

        # Template with actual username
        templated = profile_manager.template_profile(profile, "johndoe")

        assert templated.home == "/home/johndoe"
        assert templated.workspace == "/home/johndoe"
        assert templated.default_user == "johndoe"
        assert "{{ username }}" not in templated.home

    def test_detect_local_profile_macos(self, profile_manager, monkeypatch):
        """Test local profile detection on macOS"""
        monkeypatch.setattr("platform.system", lambda: "Darwin")

        profile_name = profile_manager.detect_local_profile()

        assert profile_name == "local-mac"

    def test_detect_local_profile_linux(self, profile_manager, monkeypatch):
        """Test local profile detection on Linux"""
        monkeypatch.setattr("platform.system", lambda: "Linux")

        profile_name = profile_manager.detect_local_profile()

        assert profile_name == "local-linux"

    def test_save_server_config(self, profile_manager):
        """Test saving server configuration"""
        profile_manager.initialize_config()

        server_config = {
            "host": "user@example.com",
            "profile": "generic-ubuntu"
        }

        profile_manager.save_server_config("myserver", server_config)

        # Verify saved
        assert profile_manager.servers_file.exists()

        with open(profile_manager.servers_file) as f:
            data = json.load(f)
            assert "servers" in data
            assert "myserver" in data["servers"]
            assert data["servers"]["myserver"]["host"] == "user@example.com"

    def test_get_server_config(self, profile_manager):
        """Test retrieving saved server configuration"""
        profile_manager.initialize_config()

        # Save a server config
        server_config = {
            "host": "user@example.com",
            "profile": "aws-ubuntu"
        }
        profile_manager.save_server_config("myserver", server_config)

        # Retrieve it
        retrieved = profile_manager.get_server_config("myserver")

        assert retrieved is not None
        assert retrieved["host"] == "user@example.com"
        assert retrieved["profile"] == "aws-ubuntu"

    def test_get_server_config_returns_none_for_invalid(self, profile_manager):
        """Test get_server_config returns None for nonexistent server"""
        profile_manager.initialize_config()

        retrieved = profile_manager.get_server_config("nonexistent")

        assert retrieved is None

    def test_profile_has_all_required_fields(self, profile_manager):
        """Test that all default profiles have required fields"""
        profile_manager.initialize_config()

        required_fields = [
            "name", "home", "workspace", "npm_global",
            "install_method", "default_user", "persistent_storage", "platform"
        ]

        for profile_name in ProfileManager.DEFAULT_PROFILES.keys():
            profile = profile_manager.get_profile(profile_name)
            assert profile is not None

            for field in required_fields:
                assert hasattr(profile, field)
                assert getattr(profile, field) is not None

    def test_vast_profile_configuration(self, profile_manager):
        """Test Vast.ai profile has correct configuration"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("vast-root")

        assert profile.home == "/root"
        assert profile.workspace == "/workspace"
        assert profile.persistent_storage == "/workspace"
        assert profile.default_user == "root"
        assert profile.install_method == "npm"
        assert profile.platform == "vast.ai"

    def test_lambda_profile_configuration(self, profile_manager):
        """Test Lambda Labs profile has correct configuration"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("lambda-ubuntu")

        assert profile.home == "/home/ubuntu"
        assert profile.workspace == "/home/ubuntu"
        assert profile.persistent_storage == "/lambda/nfs"
        assert profile.default_user == "ubuntu"
        assert profile.install_method == "npm"

    def test_windows_profile_configuration(self, profile_manager):
        """Test Windows profile has correct configuration"""
        profile_manager.initialize_config()
        profile = profile_manager.get_profile("local-windows")

        assert profile.home == "C:/Users/{{ username }}"
        assert profile.workspace == "C:/Users/{{ username }}/Projects"
        assert profile.persistent_storage == "C:/Users/{{ username }}"
        assert profile.default_user == "{{ username }}"
        assert profile.install_method == "native"
        assert profile.platform == "windows"

    def test_detect_local_profile_windows(self, profile_manager, monkeypatch):
        """Test Windows detection for local profile"""
        # Mock platform.system() to return Windows
        import platform
        monkeypatch.setattr(platform, "system", lambda: "Windows")

        detected = profile_manager.detect_local_profile()

        assert detected == "local-windows"
