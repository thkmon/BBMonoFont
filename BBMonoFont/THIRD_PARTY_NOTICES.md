# Build-tool notices

The repository does not vendor third-party Python source code. The following
packages are installed from PyPI only for building and validating the fonts.

## FontTools 4.63.0

- Project: <https://github.com/fonttools/fonttools>
- License: MIT and component-specific open-source licenses
- Installed version is pinned in `requirements.txt`.

## ttfautohint-py 0.6.0

- Project: <https://github.com/fonttools/ttfautohint-py>
- License: MIT
- Binary wheels contain the upstream `ttfautohint` executable and its documented
  static FreeType and HarfBuzz dependencies.
- Installed version is pinned in `requirements.txt`.

Font copyrights and licenses are documented separately in `FONT-LICENSES.md`.
