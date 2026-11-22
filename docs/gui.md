# rmpp-studio, the app

A small video editor for tablet tutorials (PySide6 / Qt 6; Windows, macOS and Linux, each release file bundles
everything).

| Area | What |
|---|---|
| **LIVE** (left monitor) | The tablet screen (in color, refreshed every second with **Live**, copied from xochitl's framebuffer so it cannot stall the display). Click = tap, hold = long press, drag = swipe; **Pen** mode: drag = pen stroke; **Look** mode or right click = list the UI items there. **⌨ Keyboard**: what you type goes to the text field focused on the tablet (tap one first): letters and Korean or other input methods (sent when a character is complete), Enter, Backspace, Delete, Tab, Escape, arrows, Home / End, Ctrl+A / C / V / X / Z / Y; one SSH connection for all keys. **Pointer** draws where the real pen (hover ring, pressure dot, stroke trail) and fingers are. |
| **PREVIEW** (right monitor) | The selected recording as it will be exported (clips, shortened pauses, captions). ⏮ ◀◀ ▶/⏸ ▶▶ ⏭ (Space, ←/→ = previous/next change, Home/End). |
| **Clips + timeline** | The recording is cut into clips that play in order: **✂ Split** at the playhead (S), **[ In / Out ]** to trim the clip under the playhead (I / O), **⧉ Duplicate** (Ctrl+D, or Ctrl+C / Ctrl+V), **🗑 Delete** (Delete; the recording keeps the frames), **↶ Undo / ↷ Redo** (Ctrl+Z / Ctrl+Shift+Z), **⟲ Reset**. Drag a clip to move it, drag its edges to trim. Thumbnails show where the screen changed; captions belong to the recording time, so they move with their clip (drag to move, double click to edit). Ctrl+wheel zooms, wheel scrolls. |
| **Recordings** (left) | Your recordings with thumbnails; rename, delete, open the folder. |
| **Tools** (right), in workflow order | **Remote** (type text, keys, quick buttons, find UI items, record actions as script steps), **Script** (`.tut` editor, run + record, try, stop, current line highlighted), **Captions** (list, time, text, add / apply / move / delete, live marks while recording with Ctrl+M), **Export** (format: MP4 / WebM / MOV / GIF / WebP / APNG; codec for videos: H.264, H.265, AV1, VP9, ProRes; quality high / medium / small; fps, size, shorten pauses, hold end; progress; exported files with sizes), **Log**. |
| **Toolbar** | Connection, ● Record (fps; Ctrl+R; stop asks for a name and opens the recording), 📷 Shot, ▶ Run script, ⇪ Export. |

Edits of a recording (clips as `segments`, captions, export settings) are saved in its `edit.json` (`rmpp-ctl render <recording> out.mp4` uses it too). Settings
(connection, last script, window layout) are kept in `%APPDATA%\rmpp-studio\studio.json` (macOS:
`~/Library/Application Support/rmpp-studio/`, Linux: `~/.config/rmpp-studio/`); recordings in `recordings/`.
