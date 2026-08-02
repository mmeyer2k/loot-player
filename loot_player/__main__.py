"""``python -m loot_player`` entrypoint.

AppRun invokes the app this way rather than through the ``loot-player``
console script, because a generated script's shebang is an absolute path
baked in at install time and does not survive relocation into an AppImage.
"""

from loot_player.app import main


if __name__ == "__main__":
    main()
