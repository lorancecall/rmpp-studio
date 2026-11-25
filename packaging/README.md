# packaging

The Vellum package of this add-on: `rmpp-remote`.
[rmpp-packages](https://github.com/lorancecall/rmpp-packages) builds, signs and publishes it from here (its
`scripts/registry.py` finds this repository by the topic `rmpp`). After a release, update `pkgver` and the
sums in the VELBUILD on the default branch; the next build (daily, or
`gh workflow run publish.yml -R lorancecall/rmpp-packages`) publishes it. Format and rules:
[MODS.md](https://github.com/lorancecall/rmpp-packages/blob/main/MODS.md).
