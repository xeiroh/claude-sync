# claude-sync

Sync your local Claude Code environment to remote machines via SSH.

## Overview

claude-sync automatically synchronizes your Claude Code configuration, agents, commands, and MCP servers to remote machines. It handles path translation across different platforms, validates compatibility, and can automatically install Claude Code on remote servers if not already present.

## Features

- **SSH-based syncing** - Secure file transfer via SFTP
- **Auto-install Claude Code** - Automatically installs matching Claude Code version on remote if missing
- **Profile-based path translation** - Automatic path mapping for 10 major platforms
- **Compatibility validation** - Checks install method and MCP server compatibility before sync
- **Smart filtering** - Syncs essential configs while skipping local-only data
- **Server configuration persistence** - Save frequently-used servers for quick access
- **Dry-run mode** - Preview sync operations without making changes

## Installation

Install via pip:

```bash
pip install -e .
```

Initialize configuration directory:

```bash
claude-sync --init
```

This creates `~/.claude-sync/` with default profiles for major cloud platforms.

## Quick Start

Sync to a remote server:

```bash
claude-sync --ssh user@hostname
```

Preview what would be synced:

```bash
claude-sync --ssh user@hostname --dry-run
```

Save server for future use:

```bash
claude-sync --ssh user@hostname --save-server myserver
claude-sync --server myserver
```

## Usage

### Basic Sync

```bash
# Auto-detect remote platform
claude-sync --ssh user@host

# With custom port
claude-sync --ssh user@host:2222

# Specify remote profile explicitly
claude-sync --ssh user@host --profile generic-ubuntu

# Verbose output
claude-sync --ssh user@host --verbose
```

### SSH Authentication

Specify custom SSH keys or use complete SSH commands:

```bash
# Use specific SSH key (long form)
claude-sync --ssh user@host --key ~/.ssh/my-custom-key

# Use specific SSH key (short form, like SSH -i)
claude-sync --ssh user@host -i ~/.ssh/my-custom-key

# Pass complete SSH command
claude-sync --ssh-command "ssh user@host"

# SSH command with key file
claude-sync --ssh-command "ssh -i ~/.ssh/my-key user@host"

# SSH command with port
claude-sync --ssh-command "ssh -p 2222 user@host"

# Complex SSH command
claude-sync --ssh-command "ssh -i ~/.ssh/my-key -p 3000 user@example.com"

# --key flag takes precedence over key in --ssh-command
claude-sync --ssh-command "ssh -i ~/.ssh/other user@host" --key ~/.ssh/priority
```

**Encrypted SSH Keys**:
- Supports password-protected (encrypted) SSH keys
- Automatically detects encrypted keys and prompts for passphrase
- Supports RSA, Ed25519, ECDSA, and DSA key types
- Passphrase prompt appears interactively when needed

```bash
# Using encrypted key - will prompt for passphrase
claude-sync --ssh user@host -i ~/.ssh/encrypted_key
# Enter passphrase for ~/.ssh/encrypted_key: [prompted securely]
```

**Authentication Priority**:
- With `--key` or `-i`: Uses specified key file
- Without `--key`: Uses SSH agent or default keys (`~/.ssh/id_rsa`, `~/.ssh/id_ed25519`, etc.)
- Saved servers: Key is stored and reused automatically

### Dry Run

Preview sync operations without making changes:

```bash
claude-sync --ssh user@host --dry-run
```

### Server Management

```bash
# Save server configuration
claude-sync --ssh user@host --profile aws-ubuntu --save-server aws-prod

# Save with custom SSH key
claude-sync --ssh user@host -i ~/.ssh/my-key --save-server my-server

# Use saved server (automatically uses saved key)
claude-sync --server aws-prod

# Dry-run with saved server
claude-sync --server aws-prod --dry-run
```

### Profile Management

```bash
# List all available profiles
claude-sync --list-profiles

# Specify local profile (auto-detected by default)
claude-sync --ssh user@host --local-profile local-mac
```

## Supported Platforms

Default profiles included for:

- **Vast.ai** - Root user, /workspace persistent storage
- **RunPod** - Root user, /workspace persistent storage
- **Lambda Labs** - Ubuntu user, /lambda/nfs persistent storage
- **Paperspace Gradient** - Paperspace user, /storage persistent
- **AWS EC2 Ubuntu** - Ubuntu user
- **Google Cloud Compute Engine** - Configurable username
- **Generic Ubuntu** - Standard Ubuntu servers
- **Generic Debian** - Standard Debian servers
- **Local macOS** - Development environment
- **Local Linux** - Development environment

## How It Works

1. **SSH Connection** - Establishes secure connection to remote server
2. **Platform Detection** - Auto-detects remote platform or uses specified profile
3. **Claude Code Check** - Verifies Claude Code installation on remote
4. **Auto-Install** - Installs Claude Code if missing, matching local version and install method
5. **Config Preparation** - Templates paths and sanitizes configs for remote environment
6. **Compatibility Validation** - Checks install method and MCP server compatibility
7. **SFTP Transfer** - Securely transfers configuration files
8. **Verification** - Confirms successful sync

## What Gets Synced

### Included Files

- `~/.claude.json` - Sanitized config (projects object removed, paths templated)
- `~/.claude/settings.json` - Settings with templated paths
- `~/.claude/agents/` - Custom agent definitions
- `~/.claude/commands/` - Slash command definitions
- `~/.claude/CLAUDE.md` - Global instructions
- `~/.claude/*.md` - Framework and mode files

### Excluded Files

- `~/.claude/projects/` - Local project histories
- `~/.claude/todos/` - Session-specific todos
- `~/.claude/logs/` - Local log files
- `~/.claude/shell-snapshots/` - Local shell state
- `~/.claude/ide/` - IDE-specific state
- `~/.claude/statsig/` - Analytics data
- `*.jsonl` - Chat history files

## Auto-Install Feature

If Claude Code is not installed on the remote server, claude-sync will:

1. Detect your local Claude Code version
2. Read your local install method (npm or native)
3. Install the same version on the remote using the same method:
   - **npm**: `npm install -g @anthropic-ai/claude-code@<version>`
   - **native**: `curl -fsSL https://claude.ai/install.sh | bash -s <version>`
4. Verify installation succeeded
5. Continue with sync

If installation fails, the sync is aborted with a clear error message.

## Compatibility Validation

Before syncing, claude-sync validates:

### Install Method Compatibility

Checks that the local `installMethod` in `~/.claude.json` is compatible with the remote profile's expected install method:

- **npm** and **native** are compatible
- Mismatches generate warnings but allow sync to continue

### MCP Server Compatibility

Validates each MCP server configuration for:

- Absolute paths in commands (won't work remotely)
- Local paths in arguments that need templating
- Command availability on remote system

Issues are reported as warnings. Critical errors abort the sync.

## Custom Profiles

Add custom profiles to `~/.claude-sync/profiles.json`:

```json
{
  "profiles": {
    "my-server": {
      "name": "My Custom Server",
      "home": "/home/{{ username }}",
      "workspace": "/home/{{ username }}/workspace",
      "npm_global": "/home/{{ username }}/.npm-global",
      "install_method": "npm",
      "default_user": "myuser",
      "persistent_storage": "/home/{{ username }}",
      "platform": "custom"
    }
  }
}
```

The `{{ username }}` placeholder is automatically replaced with the actual remote username.

## Path Translation

claude-sync automatically translates local paths to remote equivalents:

### Path Mapping Examples

| Local Path | Remote Path (Ubuntu) |
|------------|---------------------|
| `/Users/john/.claude` | `/home/ubuntu/.claude` |
| `/Users/john/Projects` | `/home/ubuntu/workspace` |
| `file:///Users/john/file.txt` | `file:///home/ubuntu/file.txt` |
| `//Users/john/**` | `//home/ubuntu/**` |

### Supported Path Formats

- Direct paths: `/Users/john/path`
- File protocol: `file:///Users/john/path`
- Permission patterns: `//Users/john/**`
- Multiple paths in single string

## Troubleshooting

### SSH Connection Issues

```bash
# Verify SSH access
ssh user@host

# Try with specific SSH key
claude-sync --ssh user@host -i ~/.ssh/my-key

# Try with explicit port
claude-sync --ssh user@host:2222

# Use complete SSH command (useful for testing)
claude-sync --ssh-command "ssh -i ~/.ssh/key -p 2222 user@host"

# Enable verbose output
claude-sync --ssh user@host --verbose
```

**Common SSH Authentication Issues**:
- Key not found: Verify key path exists (`ls ~/.ssh/my-key`)
- Permission denied: Check key permissions (`chmod 600 ~/.ssh/my-key`)
- Wrong key: Try specifying key explicitly with `--key` or `-i`
- No SSH agent: Use `--key` to specify key directly instead of relying on agent
- Encrypted key passphrase: Will prompt interactively; ensure you enter correct passphrase

### Profile Detection

```bash
# List available profiles
claude-sync --list-profiles

# Specify profile explicitly
claude-sync --ssh user@host --profile generic-ubuntu
```

### Installation Failures

If Claude Code installation fails on remote:

1. Check remote has npm or curl installed
2. Verify network connectivity on remote
3. Check disk space on remote
4. Try manual installation, then sync

### Compatibility Warnings

Review warnings carefully:

- **Install method mismatch** - May require reinstalling Claude Code on remote
- **MCP server issues** - May need to adjust MCP server configs

## Development

Install with dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest tests/
```

Run tests with coverage:

```bash
pytest tests/ --cov=claude_sync --cov-report=term-missing
```

Format code:

```bash
black claude_sync/
ruff check claude_sync/
```

## Requirements

- Python 3.10 or higher
- SSH access to remote machine
- SSH authentication via one of:
  - SSH agent with loaded keys
  - Default SSH keys (`~/.ssh/id_rsa`, `~/.ssh/id_ed25519`, etc.)
  - Custom key specified with `--key` or `-i`
  - SSH command with `--ssh-command`

### Python Dependencies

- paramiko >= 3.0.0
- jinja2 >= 3.1.0

## Security Considerations

- **API Keys**: Synced in plain text (encrypted only during SSH transport)
- **SSH Host Keys**: Auto-accepted (AutoAddPolicy) - verify host on first connection
- **SSH Keys**:
  - Stored keys are read from disk but never modified
  - Saved server configs include key paths (not key contents)
  - Use proper key permissions (`chmod 600 ~/.ssh/your-key`)
- **Authentication**: Key-based authentication only (password auth not supported)

## License

MIT

## Contributing

Contributions welcome. Please:

1. Run tests before submitting: `pytest tests/`
2. Format code: `black claude_sync/`
3. Check linting: `ruff check claude_sync/`
4. Update tests for new features

## Version

Current version: 0.1.0