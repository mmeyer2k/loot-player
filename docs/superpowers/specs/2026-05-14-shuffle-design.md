# Shuffle Modes — Design

**Status:** approved, pending implementation plan
**Date:** 2026-05-14

## Problem

The transport `⏭` button plays the next queued item or falls back to the next file in the current playback's folder (alphabetical). When the user wants randomness — to put on a TV library and let it play unpredictable episodes, or to roam between libraries — there's no path. Manually building shuffled queues is friction.

## Scope

In:
- A single shuffle-state button in the transport bar that cycles three states: Off → Within library → Between libraries → Off.
- New `⏭` (and track-end auto-advance) behavior that picks a random file from the chosen scope when shuffle is on.
- Random-pop from the queue when shuffle is on (queue items still play first; their order is randomized).
- Persistence of the shuffle state across app restarts.

Out (explicit non-goals):
- A history stack. `⏮` Prev keeps its current behavior (3-second restart, else alphabetical previous-in-folder) in all shuffle modes. There is no "previously played" history.
- Smart anti-repeat (excluding recently-played files beyond the immediately-prior one). Pure `ORDER BY RANDOM()` excluding the current file by id.
- A "Shuffle play" right-click action that fills the queue from a folder/library. The toggle covers the same use case.
- Per-library shuffle preference. One global state.
- Glyph overlay differentiation between Within and Between (color + tooltip is the only differentiator for now; if it turns out color isn't enough we can iterate).

## Behavior

### Three states, single button

The transport bar gains one slim button just to the right of `⏭`. One click cycles modes:

| State | Visual | Tooltip |
|---|---|---|
| `off` | `🔀` flat / un-checked | `Shuffle: off` |
| `within` | `🔀` checked, accent color A (yellow tint) | `Shuffle: within library` |
| `between` | `🔀` checked, accent color B (blue tint) | `Shuffle: across all libraries` |

State persists in `ui_state` under key `shuffle_mode`. Restored on startup.

### `⏭` Next and auto-advance

The same logic drives the next button, the queue panel's Next button, and the `_on_tick` auto-advance on track end.

| Mode | Behavior |
|---|---|
| `off` | Queue first (in order via `take_next()`), else `next_file_in_folder(library_id, parent_dir, filename)`. **Current behavior, unchanged.** |
| `within` | Queue first (via `take_random()`), else `random_file_in_library(library_id, exclude_id=current.id)`. |
| `between` | Queue first (via `take_random()`), else `random_file_anywhere(exclude_id=current.id)`. |

If no file is currently playing AND the queue is empty AND shuffle is on, `⏭` is a no-op. Acceptable — same as today's "no folder context" no-op.

### `⏮` Prev

Unchanged in all modes:
1. If `video.get_time() > 3000`: seek to 0, keep playing.
2. Else: `prev_file_in_folder(library_id, parent_dir, filename)` and play it.

Adding shuffle-aware prev would require a session history stack. Out of scope for v1.

### Edge cases

- **Library has only one file** (`within` mode, queue empty): `random_file_in_library` with `exclude_id=current.id` returns no row → no-op. Same outcome a user would see if alphabetical "next" hit the end.
- **All libraries combined have one file** (`between` mode, queue empty): same — no-op.
- **Orphan files** (rows with `library_id IS NULL`, possible after a botched migration): `random_file_anywhere` filters them out (`WHERE library_id IS NOT NULL`). They're invisible to "between" shuffle.
- **Current file deleted between play and `⏭`**: random query doesn't care, returns a row, plays it. Same fault tolerance as alphabetical next.
- **Toggling shuffle mid-playback**: the current track keeps playing. The new mode applies only to the next call to `_play_next` (whether from button, queue Next, or auto-advance).

## Database

Two new methods on `LibraryDB`:

```python
def random_file_in_library(self, library_id: int,
                           exclude_id: int | None = None) -> FileRow | None:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    if exclude_id is None:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id=?
                  ORDER BY RANDOM() LIMIT 1"""
        args = (library_id,)
    else:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id=? AND id != ?
                  ORDER BY RANDOM() LIMIT 1"""
        args = (library_id, exclude_id)
    row = self.conn.execute(sql, args).fetchone()
    return FileRow(*row) if row else None

def random_file_anywhere(self, exclude_id: int | None = None) -> FileRow | None:
    cols = """id, library_id, path, parent_dir, filename, ext, size, mtime, duration,
              title, year, series, season, episode, artist, album, track"""
    if exclude_id is None:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id IS NOT NULL
                  ORDER BY RANDOM() LIMIT 1"""
        args = ()
    else:
        sql = f"""SELECT {cols} FROM files
                  WHERE library_id IS NOT NULL AND id != ?
                  ORDER BY RANDOM() LIMIT 1"""
        args = (exclude_id,)
    row = self.conn.execute(sql, args).fetchone()
    return FileRow(*row) if row else None
```

`ORDER BY RANDOM() LIMIT 1` is fine for personal-library scale (tens of thousands of files). No new index needed — SQLite scans `idx_files_library` for the within case and a full scan for between, but the limit-1 cuts execution short in practice.

## Queue model

One new method on `QueueModel`:

```python
def take_random(self) -> Optional[FileRow]:
    """Pop and return a random file from the queue, or None if empty."""
    if not self._files:
        return None
    import random
    idx = random.randrange(len(self._files))
    f = self._files.pop(idx)
    self._rebuild()
    return f
```

(The `import random` stays inside the method to avoid adding it at module top; the rest of `models.py` doesn't need it.)

## MainWindow

State:

```python
self._shuffle_mode: str = "off"  # "off" | "within" | "between"
```

Read from `ui_state["shuffle_mode"]` in `_restore_state`; default `"off"` if missing or invalid.

`_play_next` becomes:

```python
def _play_next(self):
    """Transport ⏭: respect shuffle mode."""
    f = self._take_next_for_mode()
    if f is None:
        return
    self._play(f)

def _take_next_for_mode(self) -> Optional[FileRow]:
    if self._shuffle_mode == "off":
        f = self.queue_model.take_next()
        self._persist_queue()
        if f:
            return f
        cur = self.current_file
        if cur is None or cur.library_id is None:
            return None
        return self.db.next_file_in_folder(cur.library_id, cur.parent_dir, cur.filename)

    # Shuffle on: random pop from queue first.
    f = self.queue_model.take_random()
    self._persist_queue()
    if f:
        return f
    cur = self.current_file
    if cur is None:
        return None
    if self._shuffle_mode == "within":
        if cur.library_id is None:
            return None
        return self.db.random_file_in_library(cur.library_id, exclude_id=cur.id)
    if self._shuffle_mode == "between":
        return self.db.random_file_anywhere(exclude_id=cur.id)
    return None
```

The auto-advance branch in `_on_tick` already calls `_play_next` — no change there.

## UI: the shuffle button

In `_build_transport_bar`, between the `next_btn` creation and the `time_label`:

```python
self.shuffle_btn = slim_button(text="🔀", slot=self._cycle_shuffle)
self.shuffle_btn.setFixedWidth(28)
self.shuffle_btn.setCheckable(True)
row.addWidget(self.shuffle_btn)
```

New handler in `MainWindow`:

```python
_SHUFFLE_CYCLE = ["off", "within", "between"]
_SHUFFLE_STYLES = {
    "off":     ("",                                          "Shuffle: off"),
    "within":  ("background-color: rgba(255, 200, 0, 0.25);", "Shuffle: within library"),
    "between": ("background-color: rgba(0, 150, 255, 0.30);", "Shuffle: across all libraries"),
}

def _cycle_shuffle(self):
    idx = self._SHUFFLE_CYCLE.index(self._shuffle_mode)
    self._shuffle_mode = self._SHUFFLE_CYCLE[(idx + 1) % len(self._SHUFFLE_CYCLE)]
    self._apply_shuffle_visual()
    self.db.ui_set("shuffle_mode", self._shuffle_mode)

def _apply_shuffle_visual(self):
    style, tip = self._SHUFFLE_STYLES[self._shuffle_mode]
    self.shuffle_btn.setStyleSheet(style)
    self.shuffle_btn.setToolTip(tip)
    self.shuffle_btn.setChecked(self._shuffle_mode != "off")
```

The button toggles its `checked` state through `setChecked`, so Qt renders a "sunken" look when active. Stylesheet adds a colored tint per mode. Tooltip names the mode.

`_restore_state` reads the persisted mode and calls `_apply_shuffle_visual()` once.

## Implementation order

The plan should run in this order:
1. DB helpers + pytest coverage for them (random returns valid file rows; respects scope; honors exclude).
2. `QueueModel.take_random()` (no tests — trivial, would need PyQt fixtures).
3. `_take_next_for_mode` + refactor of `_play_next` (no separate tests; smoke-test by toggling the button).
4. Shuffle button in transport bar + cycle handler + persistence.

## Testing

Pytest for the two new DB helpers:
- `random_file_in_library` returns a row matching `library_id`, never returns the excluded id, returns None when only the excluded id exists.
- `random_file_anywhere` returns rows from any library, never returns the excluded id, ignores `library_id IS NULL` rows.

Manual smoke-test after implementation:
- Cycle shuffle button: tooltip + visual update visibly per click.
- Play a file from library A; press `⏭` with shuffle = within → file from library A plays (different from current).
- Press `⏭` with shuffle = between → file from anywhere plays.
- Add three items to queue, shuffle = within → press `⏭` three times → all three play in random order, then folder-scoped or library-scoped random takes over.
- Restart the app → shuffle mode and button visual restored.

## What stays the same

- Right-click "Queue end / Queue front / Play next" — items added in tree order.
- `⏮` Prev semantics.
- Queue persistence; FTS5 search; scanner; matching; cinema/fullscreen; click-to-seek; bold-playing-item.

## Open questions / risks

- **Color-only differentiation** between Within and Between. If it proves insufficient in real use, follow-up: add a small letter overlay (`🔀ⓛ` / `🔀ⓖ`) or a glyph difference. Defer until felt.
- **`ORDER BY RANDOM()` at scale.** For libraries of hundreds of thousands of files, this scans the full set on every `⏭`. A future optimization could cache random row IDs or use a "shuffle queue" populated lazily. Not a v1 concern.
