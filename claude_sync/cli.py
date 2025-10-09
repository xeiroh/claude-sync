#!/usr/bin/env python3
"""
Command-line interface for claude-sync
"""

import argparse
import sys
from typing import Optional

from claude_sync.profiles import ProfileManager
from claude_sync.sync import SyncManager


def parse_ssh_command(ssh_command: str) -> tuple[str, Optional[str]]:
    """
    Parse SSH command to extract target and key file

    Args:
        ssh_command: Full SSH command (e.g., 'ssh -i ~/.ssh/key user@host -p 2222')

    Returns:
        Tuple of (ssh_target, key_file)
        ssh_target format: user@host or user@host:port
        key_file: Path to SSH key or None
    """
    import shlex

    # Split command into parts
    parts = shlex.split(ssh_command)

    # Remove 'ssh' command if present
    if parts and parts[0] == 'ssh':
        parts = parts[1:]

    ssh_target = None
    key_file = None
    port = None

    i = 0
    while i < len(parts):
        part = parts[i]

        # Check for -i or --identity flag for key file
        if part in ['-i', '--identity']:
            if i + 1 < len(parts):
                key_file = parts[i + 1]
                i += 2
                continue

        # Check for -p or --port flag
        elif part in ['-p', '--port']:
            if i + 1 < len(parts):
                port = parts[i + 1]
                i += 2
                continue

        # Check for combined short flags (e.g., -i/path/to/key)
        elif part.startswith('-i'):
            # Format: -i/path or -ipath
            key_file = part[2:]
            i += 1
            continue

        # Skip other flags
        elif part.startswith('-'):
            # Unknown flag, try to skip it and its value if it takes one
            if i + 1 < len(parts) and not parts[i + 1].startswith('-'):
                i += 2
            else:
                i += 1
            continue

        # This should be the target (user@host)
        else:
            ssh_target = part
            i += 1

    if not ssh_target:
        raise ValueError(f"Could not extract SSH target from command: {ssh_command}")

    # Add port to target if specified
    if port:
        ssh_target = f"{ssh_target}:{port}"

    return ssh_target, key_file


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser"""
    parser = argparse.ArgumentParser(
        prog="claude-sync",
        description="Sync local Claude Code environment to remote machines"
    )

    # Remote target options (mutually exclusive)
    # NOTE: Not required=True because --init and --list-profiles don't need a target
    target_group = parser.add_mutually_exclusive_group(required=False)
    target_group.add_argument(
        "--ssh",
        type=str,
        metavar="SSH_TARGET",
        help="Sync via SSH (e.g., user@host:port or just user@host)"
    )
    target_group.add_argument(
        "--ssh-command",
        type=str,
        metavar="SSH_COMMAND",
        help="Sync using full SSH command (e.g., 'ssh -i ~/.ssh/key user@host -p 2222')"
    )
    target_group.add_argument(
        "--server",
        type=str,
        metavar="SERVER_NAME",
        help="Use saved server configuration"
    )

    # Profile options
    parser.add_argument(
        "--profile",
        type=str,
        help="Specify remote profile (e.g., vast-root, runpod-root, lambda-ubuntu)"
    )
    parser.add_argument(
        "--local-profile",
        type=str,
        help="Specify local profile (default: auto-detect)"
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profiles and exit"
    )

    # Sync options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without making changes"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode with prompts for profile selection"
    )
    parser.add_argument(
        "--key",
        "-i",
        type=str,
        metavar="KEY_FILE",
        help="Path to SSH private key file (e.g., ~/.ssh/id_rsa)"
    )

    # Server management
    parser.add_argument(
        "--save-server",
        type=str,
        metavar="NAME",
        help="Save current connection as named server config"
    )

    # Initialization
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize ~/.claude-sync directory with default profiles"
    )

    return parser


def list_profiles(profile_manager: ProfileManager) -> None:
    """Display available profiles"""
    profiles = profile_manager.load_profiles()

    print("\nAvailable Profiles:\n")
    for name, profile in profiles.items():
        print(f"  {name}:")
        print(f"    Platform: {profile.get('platform', 'unknown')}")
        print(f"    Home: {profile.get('home', 'N/A')}")
        print(f"    Workspace: {profile.get('workspace', 'N/A')}")
        print(f"    User: {profile.get('default_user', 'N/A')}")
        if 'note' in profile:
            print(f"    Note: {profile['note']}")
        print()


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for CLI"""
    parser = create_parser()
    args = parser.parse_args(argv)

    # Initialize profile manager
    profile_manager = ProfileManager()

    # Handle --init
    if args.init:
        print("Initializing ~/.claude-sync directory...")
        profile_manager.initialize_config()
        print(f"Created config directory at: {profile_manager.config_dir}")
        print(f"Default profiles saved to: {profile_manager.profiles_file}")
        print("\nRun 'claude-sync --list-profiles' to see available profiles")
        return 0

    # Handle --list-profiles
    if args.list_profiles:
        list_profiles(profile_manager)
        return 0

    # Validate that user provided a sync target (since target_group is not required)
    if not args.ssh and not args.ssh_command and not args.server:
        parser.error("One of --ssh, --ssh-command, or --server is required for syncing. Use --init to initialize or --list-profiles to view profiles.")

    try:
        # Ensure config is initialized
        profile_manager.initialize_config()

        # Determine local profile
        if args.local_profile:
            local_profile_name = args.local_profile
        else:
            local_profile_name = profile_manager.detect_local_profile()
            if args.verbose:
                print(f"Auto-detected local profile: {local_profile_name}")

        local_profile = profile_manager.get_profile(local_profile_name)
        if not local_profile:
            print(f"Error: Profile '{local_profile_name}' not found", file=sys.stderr)
            return 1

        # Template local profile if needed (replace {{ username }})
        import os
        local_username = os.getenv('USER') or os.path.basename(os.path.expanduser('~'))
        local_profile = profile_manager.template_profile(local_profile, local_username)

        # Initialize sync manager
        sync_manager = SyncManager(
            profile_manager=profile_manager,
            local_profile=local_profile,
            dry_run=args.dry_run,
            verbose=args.verbose
        )

        # Determine sync target and execute
        if args.ssh or args.ssh_command:
            # Determine SSH target and key file
            if args.ssh_command:
                # Parse SSH command
                ssh_target, parsed_key = parse_ssh_command(args.ssh_command)
                # --key flag takes precedence over parsed key from command
                key_file = args.key if args.key else parsed_key
            else:
                # Regular --ssh target
                ssh_target = args.ssh
                key_file = args.key

            sync_manager.sync_to_ssh(
                ssh_target=ssh_target,
                remote_profile=args.profile,
                interactive=args.interactive,
                key_file=key_file
            )
        elif args.server:
            server_config = profile_manager.get_server_config(args.server)
            if not server_config:
                print(f"Error: Server '{args.server}' not found in config", file=sys.stderr)
                print("Run 'claude-sync --ssh user@host --save-server NAME' to save a server", file=sys.stderr)
                return 1

            sync_manager.sync_to_saved_server(server_config)

        # Save server config if requested
        if args.save_server:
            # Validation: --save-server only works with --ssh or --ssh-command
            if not args.ssh and not args.ssh_command:
                print("Error: --save-server can only be used with --ssh or --ssh-command", file=sys.stderr)
                print("Example: claude-sync --ssh user@host --save-server myserver", file=sys.stderr)
                return 1

            # Use the determined ssh_target from above
            server_config = {
                'host': ssh_target,
                'profile': args.profile or 'auto-detect',
                'key': key_file
            }
            profile_manager.save_server_config(args.save_server, server_config)
            print(f"\nSaved server config as: {args.save_server}")

        return 0

    except KeyboardInterrupt:
        print("\n\nSync cancelled by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
