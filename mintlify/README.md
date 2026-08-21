# Agora documentation (Mintlify)

The Mintlify source for the Agora docs. Fourteen pages covering concepts, guides and reference.

## Preview locally

```bash
npm i -g mint
cd mintlify
mint dev
```

Opens on http://localhost:3000 with hot reload.

## Deploy

Connect this repository in the Mintlify dashboard and set the content directory to `mintlify/`.
Pushes to `main` then publish automatically.

## Relationship to `docs/`

`docs/` is a self-contained hand-written HTML site published via GitHub Pages, with no build step
and no dependencies — it is the fallback that works even when Actions is unavailable.

`mintlify/` is the richer product documentation: search, tabs, accordions, per-OS install tabs and
a structured tool reference.

Both describe the same software. When you change behaviour, update both — the facts they state
(19 tools, 28 tests, the lease and encoding semantics) are asserted by CI and by the test suite.
