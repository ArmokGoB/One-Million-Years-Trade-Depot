# Third-party notices

## nms_namegen (MIT License)

Source: https://github.com/hadsh/nms_namegen (a fork of https://github.com/stuart/nms_namegen), commit `52ad48affaa4089c8f487a470a888dc9b7a650aa`.

Used in this repository:

- `src/core/prng.ts`, `iprng.ts`, `voxel.ts`, `system.ts`, `region.ts`, `planet.ts` and `namegen.ts`: ported from its Python modules.
- `src/core/data/name-tables.json`: its name-generation tables, flattened by `tools/build_name_tables.py`.
- `tests/fixtures/golden-vectors.json`: its golden test vectors, reformatted by `tools/convert_golden_vectors.py`.

```
MIT License

Copyright (c) 2026 Stuart Coyle & had.sh & GGF


Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Fonts (SIL Open Font License 1.1)

Installed from npm and bundled into the built site; each package ships its full license text.

- Big Shoulders Stencil Display, via `@fontsource/big-shoulders-stencil-display`.
- Atkinson Hyperlegible Next, Copyright 2020-2024 The Atkinson Hyperlegible Next Project Authors, via `@fontsource-variable/atkinson-hyperlegible-next`.
