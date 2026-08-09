---
name: release
description: Cut a release of loot-player. Verifies the build locally, bumps the version, commits and tags, then stops before pushing. Use when the user asks to cut, ship, or tag a release, or invokes /release.
---

# Release

Cut a release. **Verify, then tag** — a tag is public and permanent, and a red
CI run on a pushed tag leaves you deleting tags or burning a version number.

**This skill never pushes.** It stops with the tag sitting locally and prints
the push command. Pushing is the human's call.

## Arguments

| Invocation | Result |
|---|---|
| `/release patch` | 0.0.0 becomes 0.0.1 |
| `/release minor` | 0.0.0 becomes 0.1.0 |
| `/release major` | 0.0.0 becomes 1.0.0 |
| `/release 0.4.2` | exactly 0.4.2 |
| `/release` | ask which of patch/minor/major |
| add `--dry-run` | everything except the commit and tag |

**Never compute the version yourself.** `packaging/release_version.py` exists
because the arithmetic looks trivial and is not: 0.9.0 + minor is 0.10.0, not
1.0.0, and `"0.10.0" > "0.9.0"` is false as a string comparison. It is covered
by `tests/test_release_version.py`. Use it.

## Step 1: Preflight

All of it before the seven-minute build, so failures are cheap.

```bash
git status --porcelain                  # must be empty
git branch --show-current               # must be master
python3 -m pytest tests/ -q             # must pass
```

Then resolve the target version:

```bash
CURRENT=$(./packaging/release_version.py current)
# bump keyword:
TARGET=$(./packaging/release_version.py bump patch)
# or an explicit version, which must still validate:
./packaging/release_version.py newer "$TARGET" 0.0.0 >/dev/null   # syntax check
```

And check it against the tags, which are the real source of truth for what has
shipped — not `version.py`, which is only the current working value:

```bash
git fetch --tags origin                       # ok to fail offline; say so if it does
git tag -l "v$TARGET"                         # must be empty
git ls-remote --tags origin "refs/tags/v$TARGET"   # must be empty
LATEST=$(git tag -l 'v*' | sed 's/^v//' | sort -V | tail -1)
[ -n "$LATEST" ] && ./packaging/release_version.py newer "$TARGET" "$LATEST"
```

If there are no tags yet, any valid version is acceptable, including one lower
than what `version.py` currently says. That is how the first release works.

**Stop and ask** if: the tree is dirty, you are not on master, master is behind
`origin/master`, the tag already exists, or the target is not newer than the
latest tag. Do not work around any of these.

## Step 2: Verify

Bump the file first, then build. The build names the artifact from
`version.py`, so building before the bump produces a file named for the wrong
release.

```bash
./packaging/release_version.py set "$TARGET"    # working tree only, NOT committed
make appimage                                   # ~7 minutes
make appimage-sweep                             # must report 0 failures
```

Confirm the artifact carries the version, in a temp dir so the extraction does
not accumulate in `/tmp`:

```bash
tmp=$(mktemp -d)
TMPDIR="$tmp" ./dist/loot-$TARGET-x86_64.AppImage --appimage-extract-and-run --version
rm -rf "$tmp"
```

Expected: `loot $TARGET`.

**If any of this fails, restore and stop:**

```bash
git checkout -- loot_player/version.py
```

Report what failed. Do not tag a build you could not verify.

## Step 3: Commit and tag

Skip this entire step on `--dry-run`; restore `version.py` and report what
would have happened.

```bash
git add loot_player/version.py
git commit -m "chore(release): v$TARGET"
git tag -a "v$TARGET" -m "loot v$TARGET"
```

**When there is nothing to commit.** If `version.py` already holds the target
and is already committed, `git commit` fails with "nothing to commit" and that
is correct, not an error to route around. It happens on a first release, where
the file was set to the starting version before any tag existed. Skip the
commit and tag HEAD directly — the tree already declares the version. Do not
fabricate an empty commit to keep the shape uniform.

```bash
if git diff --quiet HEAD -- loot_player/version.py; then
    echo "version.py already at $TARGET, tagging HEAD"
else
    git add loot_player/version.py
    git commit -m "chore(release): v$TARGET"
fi
git tag -a "v$TARGET" -m "loot v$TARGET"
```

## Step 4: Stop

Print, and do not run:

```bash
git push --follow-tags origin master
```

Tell the user what pushing will do: the `v*` tag triggers
`.github/workflows/appimage.yml`, which rebuilds from scratch, runs the unit
tests, both dlopen sweeps and both smoke tests, and publishes the AppImage to
GitHub Releases.

Say plainly that local verification reduces the risk of a bad tag but does not
eliminate it: CI rebuilds, and `pyproject.toml` pins no dependency versions, so
CI can resolve a different PyQt6 than this machine did. The local run verified
*a* build, not *the* build.

## If it goes wrong after tagging but before pushing

```bash
git tag -d "v$TARGET"
git reset --hard HEAD~1
```

Nothing has left the machine, so this is clean. After a push it is not — that
needs a `--delete` on the remote tag and a deleted GitHub release, so it is the
user's decision, not yours.
