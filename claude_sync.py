#!/usr/bin/env python3
"""
Claude Sync - Sync local Claude Code environment to remote machines

This is a convenience entry point for running claude-sync directly
without installation. For production use, install via pip and use
the 'claude-sync' command.
"""

from claude_sync.cli import main

if __name__ == "__main__":
    main()
