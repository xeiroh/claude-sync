# Changelog

All notable changes to claude-sync will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-10-08

### Added
- SSH-based syncing to remote machines via SFTP
- Profile-based path translation system with 10 default profiles
- Automatic Claude Code installation on remote servers
- Version matching between local and remote Claude Code installations
- Pre-sync compatibility validation for install methods and MCP servers
- Support for npm and native install methods
- Auto-detection of remote platform type
- Saved server configurations for quick reuse
- Dry-run mode for previewing sync operations
- Comprehensive test suite with 83 tests and 53% code coverage
- Professional documentation (README.md and CLAUDE.md)

### Features
- **Profile System**: 10 default profiles for major cloud platforms (Vast.ai, RunPod, Lambda Labs, Paperspace, AWS, GCP, Ubuntu, Debian, macOS, Linux)
- **Path Translation**: Automatic path mapping using Jinja2 templating with {{ username }} support
- **File Filtering**: Smart sync logic that skips local-only data (projects, todos, logs, shell-snapshots, IDE state, chat histories)
- **Config Sanitization**: Removes local project references, templates all paths for remote environment
- **Install Method Validation**: Checks compatibility between local installMethod and remote install_method
- **MCP Server Validation**: Validates MCP server configurations for absolute paths and compatibility issues
- **Auto-Install Process**:
  - Detects local Claude Code version
  - Checks remote installation status
  - Installs matching version using same method
  - Verifies installation success
- **CLI Features**:
  - `--init`: Initialize configuration directory
  - `--ssh user@host[:port]`: SSH-based syncing
  - `--server name`: Use saved server configuration
  - `--profile name`: Specify remote profile
  - `--local-profile name`: Specify local profile
  - `--list-profiles`: List available profiles
  - `--dry-run`: Preview sync without changes
  - `--verbose`: Detailed output
  - `--save-server name`: Save server for reuse

### Technical Implementation
- **ProfileManager**: Server environment profile management with auto-detection
- **ConfigTemplater**: Jinja2-based path translation engine
- **CompatibilityChecker**: Config sanitization and validation
- **SyncManager**: SSH/SFTP-based file transfer with auto-install
- **CLI**: argparse-based command-line interface

### Security
- SSH uses paramiko with AutoAddPolicy
- API keys and tokens synced in plain text (encrypted during SSH transport)
- No encryption beyond SSH/SFTP transport layer

### Testing
- 83 comprehensive tests across 5 test suites:
  - test_templates.py: Path templating (12 tests)
  - test_profiles.py: Profile management (15 tests)
  - test_compatibility.py: Validation (23 tests)
  - test_sync.py: SSH operations (16 tests)
  - test_cli.py: CLI interface (17 tests)
- 53% code coverage with pytest-cov

### Requirements
- Python 3.10+
- paramiko >= 3.0.0
- jinja2 >= 3.1.0
- SSH access to remote machine
- SSH key-based authentication (recommended)

## [0.0.1] - 2025-10-01

### Added
- Initial project structure
- Basic profile system prototype
- Path templating proof of concept

---

## Version History

### 0.1.0 (2025-10-08)
First stable release with SSH syncing, auto-install, and compatibility validation.

### 0.0.1 (2025-10-01)
Initial development version.
