# Next / Prev Button Behavior — Design

**Status:** approved, pending implementation plan
**Date:** 2026-05-13

## Problem

The transport bar has a "next" button (`⏭`) that pops the next file from the persistent queue and plays it. If the queue is empty, the button does nothing. There is no "prev" button. This is incomplete for everyday playback: most of the time the user isn't building a manual queue — they're playing through a folder and want to step forward to the next episode/track, or back to the previous one.

## Scope

In:
- Replace `_play_next_from_queue` semantics with a `_play_next` that prefers the queue and falls back to the next folder neighbor.
- Add a `⏮` button to the left of `⏯` in the transport bar.
- Add a `_play_prev` that follows the standard music-player "restart current vs. previous file" rule based on playback position.
- Two new DB helpers on `LibraryDB` to find adjacent files within the same library + folder.

Out (explicit non-goals):
- Cross-folder smart-next (e.g. S01E10 → S02E01). Folder neighbors only.
- Playback history / browser-style back-forward stack.
- TV-aware or music-aware navigation (already considered and rejected in favor of folder neighbors).
- Keyboard shortcuts for prev/next (can be added later; not required now).

## Behavior

### `⏭` Next
1. If the queue is non-empty: pop the front item and play it (current behavior).
2. Else if a file is currently playing: query `next_file_in_folder(library_id, parent_dir, filename)`. If a row is returned, play it.
3. Else: no-op.

### `⏮` Prev
1. If a file is currently playing AND its position > 3 seconds: seek to 0 (restart from beginning), continue playing. Do NOT touch the queue.
2. Else if a file is currently playing: query `prev_file_in_folder(library_id, parent_dir, filename)`. If a row is returned, play it.
3. Else: no-op.

The queue takes precedence on `next` because the user explicitly built it; on `prev` the queue is irrelevant because the queue is forward-only and has no concept of "the thing I just played."

### Position threshold

3000 milliseconds (3 seconds) is the cutoff between "user wants to restart current" and "user wants the actual previous file." If the player reports an invalid position (e.g., `get_time() < 0` before media has fully loaded), fall back to the "play previous file" branch.

### Edge cases

- **Nothing playing.** Both buttons are no-ops.
- **At folder boundary.** Last file in folder: next falls through to no-op. First file in folder: prev falls through to no-op. The user navigates across folders via the tree.
- **Movies (one file per folder).** Prev/next will usually be no-ops. Acceptable.
- **Current file deleted between play and button press.** Folder lookup returns no row → no-op.
- **No `library_id` on the current file.** Shouldn't happen with v1 schema, but if it does, treat as "nothing playing" — no-op.

## Database

Two new methods on `LibraryDB`:

```python
def next_file_in_folder(self, library_id: int, parent_dir: str,
                        filename: str) -> FileRow | None:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    row = self.conn.execute(
        f"""SELECT {cols} FROM files
            WHERE library_id=? AND parent_dir=? AND filename > ?
            ORDER BY filename ASC LIMIT 1""",
        (library_id, parent_dir, filename),
    ).fetchone()
    return FileRow(*row) if row else None


def prev_file_in_folder(self, library_id: int, parent_dir: str,
                        filename: str) -> FileRow | None:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    row = self.conn.execute(
        f"""SELECT {cols} FROM files
            WHERE library_id=? AND parent_dir=? AND filename < ?
            ORDER BY filename DESC LIMIT 1""",
        (library_id, parent_dir, filename),
    ).fetchone()
    return FileRow(*row) if row else None
```

The existing `idx_files_parent` index on `parent_dir` covers these queries — no new index needed.

## UI

In `MainWindow._build_transport_bar`, add a new slim button between the layout start and the play/pause button:

```python
self.prev_btn = slim_button(QStyle.StandardPixmap.SP_MediaSkipBackward, slot=self._play_prev)
self.prev_btn.setFixedWidth(28)
row.addWidget(self.prev_btn)
```

Final transport-row order: `⏮ ⏯ ⏹ ⏭ | time | spacer | 🔊 [volume] | ⛶`.

## Handler logic (in `MainWindow`)

Rename `_play_next_from_queue` to `_play_next`:

```python
def _play_next(self):
    f = self.queue_model.take_next()
    self._persist_queue()
    if f:
        self._play(f)
        return
    # Queue empty: try the next folder neighbor.
    cur = self.current_file
    if cur is None or cur.library_id is None:
        return
    nxt = self.db.next_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)
    if nxt:
        self._play(nxt)


def _play_prev(self):
    cur = self.current_file
    if cur is None:
        return
    # Restart-from-beginning rule.
    if self.video.get_time() > 3000:
        self.video.set_position(0.0)
        return
    if cur.library_id is None:
        return
    prv = self.db.prev_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)
    if prv:
        self._play(prv)
```

Update existing call sites:
- `self._on_tick` (auto-advance when current ends): `_play_next_from_queue` → `_play_next`.
- The next button in `_build_transport_bar`: `_play_next_from_queue` → `_play_next`.
- The queue panel's `play_next_requested` signal handler: `_play_next_from_queue` → `_play_next`.
- Delete the old `_play_next_from_queue` method (its body is now folded into the new `_play_next`).

The pre-existing `_play_next(files: list[FileRow])` method, which prepends to the queue and is wired to `self.tree.play_next_requested`, collides with the new no-arg `_play_next`. Resolve by renaming:
- Existing `_play_next(files)` → `_queue_play_next(files)`.
- Update `self.tree.play_next_requested.connect(self._play_next)` → `.connect(self._queue_play_next)`.

Final naming after this change:
- `_play_next()` — transport button + auto-advance. Queue first, then folder neighbor.
- `_play_prev()` — transport button. Restart-vs-prev rule, then folder neighbor.
- `_queue_play_next(files)` — tree right-click action. Prepends to the queue.

## Testing

No new automated tests. The two DB helpers are simple enough to verify by inspection; the UI behavior is exercised by clicking. Manual smoke test after implementation:

1. Open a library, double-click a file in the middle of a folder, confirm playback.
2. Click `⏭` with an empty queue → next alphabetical file plays.
3. Click `⏭` at the last file → no-op (button click does nothing).
4. Click `⏮` immediately after a file starts → previous file plays.
5. Let a file play for 5 seconds, click `⏮` → restarts from the beginning.
6. Add an item to the queue, click `⏭` → queue item plays (not the folder neighbor).
7. Empty the queue (or wait for it to drain), click `⏭` again → folder neighbor.

## What stays the same

- Queue persistence, queue-panel auto-show, FTS5 search, scanner, parsed columns, fullscreen / cinema mode, transport bar layout (apart from the one new button).
- Auto-advance on track-end keeps using the same `_play_next` (so the queue-then-folder fallback also drives auto-advance).
