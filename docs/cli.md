# rmpp-ctl: command line and tutorial scripts

`rmpp-ctl` is on PATH after installing ([docs/install.md](install.md)); from a checkout without installing, use
`python rmpp-ctl.py` instead.

```sh
export RMPP_HOST=rmpp      # ssh host alias (default "rmpp")
rmpp-ctl info                          # window size, focused item, recording state
rmpp-ctl shot screen.png
rmpp-ctl tree | find "Notebook" | hit 56 840 | props '#undoButton'
rmpp-ctl tap 800 1200 | tap '#undoButton' | tap '"Create"' | longpress X Y [ms] | swipe X1 Y1 X2 Y2 [ms]
rmpp-ctl draw circle 700 600 180 | draw rect 950 450 1350 750 | draw arrow X1 Y1 X2 Y2
rmpp-ctl draw points 100,100 300,120 500,400 | line X1 Y1 X2 Y2 [pressure]
rmpp-ctl lasso 450 350 1450 850        # with the selection tool active
rmpp-ctl text "hello 안녕" | key enter | key backspace | key ctrl+a
rmpp-ctl expect '#selectionButton' 5000
rmpp-ctl record start 4 ; ... ; rmpp-ctl record mark "A caption" ; ... ; rmpp-ctl record stop out.gif
rmpp-ctl input < script.txt            # raw Paper Pro script (below), one ssh call
rmpp-ctl run tutorials/lasso-move.tut -o out/lasso-move.gif,out/lasso-move.mp4   # videos need ffmpeg (PATH, $FFMPEG or winget)
rmpp-ctl render recordings/<name> out/demo.webm --codec av1 --quality small   # .mp4 .webm .mov .gif .webp .apng
```

UI queries (`find`, `tap`, `expect`, `prop`): `#objectName`, `"exact text"`, or words that must all appear in the
item's description as printed by `tree` (class, `#objectName`, `"text"`, `icon=name`), e.g. `Button icon=trashcan`.
`tap <query>` uses the top-most visible match and refuses if another item is painted over its center.

Coordinates are xochitl window pixels: portrait 1620 x 2160, origin top left, the same as in screenshots.

## Paper Pro script (`rmpp-remote` on the Paper Pro)

```
tap X Y [ms] | longpress X Y [ms] | swipe X1 Y1 X2 Y2 [ms]
touch down|move X Y [slot] | touch up [slot]                  multitouch, slots 0-9
pen down|move X Y [P] | pen hover X Y | pen up | pen out       P = pressure 0..1
stroke [P] [speed] : X,Y[,P] X,Y[,P] ...                      polyline, interpolated at speed px/s
line X1 Y1 X2 Y2 [P] [speed]
eraser on|off
sleep MS
raw pen|touch TYPE CODE VALUE
ui <add-on command>
```

## Add-on commands (`rmpp-remote ui <command>` on the Paper Pro)

`ping`, `info`, `source [fb|window|screen]`, `epfb`, `load <exp.so> [arg]`, `shot [path.png] [gray]`, `rec start [dir] [fps] [gray]`, `rec mark <text>`, `rec stop`, `tree [depth]`,
`find <query>`, `center <query>`, `hit X Y`, `prop <name> <query>`, `props <query>`, `text <utf8>`,
`key [ctrl+|shift+|alt+]<name>`, `pointers`.

A recording is a folder with `f000000.png ...` (only changed frames) and `frames.txt` (`<ms> <file>` per sample,
`<ms> # <caption>` per mark); `rmpp-ctl render <folder> out.gif` re-encodes kept frames (`--keep-frames DIR`).
