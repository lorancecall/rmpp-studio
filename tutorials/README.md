# Tutorial scripts (`.tut`)

A tutorial is a text file with one step per line. Steps use the same words as `rmpp-ctl` commands; a few lines
are settings or tutorial-only steps. Run and record it with:

```sh
rmpp-ctl run tutorials/lasso-move.tut                         # output from the file, else <name>.gif
rmpp-ctl run tutorials/lasso-move.tut -o out/demo.gif,out/demo.mp4 --keep-frames out/demo-frames
```

| Line | Meaning |
|---|---|
| `# ...` | comment |
| `title: ...`, `output: path.gif` | name, default output (comma separated for several formats) |
| `fps: 4` | capture rate on the tablet (frames are only stored when the screen changed) |
| `out-fps: 8`, `scale: 0.5` | output frame rate and size (0.5 = 810 x 1080) |
| `setup <command>` | runs before recording starts (open the right notebook, pick a tool, clean the page) |
| `open "<notebook>"` | close the open document and open this notebook from My files (start every tutorial with it) |
| `caption <text>` | caption shown from now on, burned into the video; `caption` alone clears it |
| `expect <query> [ms]` | wait until a UI item matches; stops the tutorial (and the recording) if it does not |
| `wait <ms>` | pause; recorded, so viewers can follow |
| anything else | an `rmpp-ctl` command: `tap`, `draw`, `lasso`, `swipe`, `text`, `key`, `line`, `ui ...` |

Recording starts at the first line that is not `setup` and stops at the end (also when a step fails). Frames are
pulled to the PC and encoded there: GIF with Pillow, MP4 with ffmpeg (if installed).

Tips:
- Begin with `setup expect ...` for the screen the tutorial needs, so a wrong screen stops it before anything is drawn.
- Find queries with `rmpp-ctl tree` (or `find <words>`) on the screen in question.
- Leave `wait` after each action: e-paper updates and xochitl's animations take a moment, and viewers need time to read.
