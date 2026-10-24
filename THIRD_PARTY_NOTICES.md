# Third-party notices

The root MIT licence applies to this project's original code and documentation. It does not replace licences of dependencies, their bundled components or any future imported datasets.

## Runtime dependencies

The package metadata for the pinned SUMO 1.28.0 packages declares **`EPL-2.0 OR GPL-2.0-or-later`**:

- `eclipse-sumo`: simulation engine and network tools.
- `sumo-data`: runtime data, installed transitively.
- `traci`: Python control interface.
- `sumolib`: Python helpers.

Upstream: [Eclipse SUMO](https://github.com/eclipse-sumo/sumo). See its [licence](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/LICENSE), [notices](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/NOTICE.md) and [libraries/licences documentation](https://sumo.dlr.de/docs/Libraries_Licenses.html). The installed packages retain their own licence and notice files. A wheel may contain additional third-party components; its distribution's notices remain authoritative.

This repository references these packages through dependency manifests and invokes the engine; it does not vendor or relicense their source code or binaries. Anyone redistributing those packages or a combined binary distribution must check and fulfil the applicable upstream terms.

## Development dependencies

- [pytest](https://github.com/pytest-dev/pytest): MIT.
- [Playwright](https://github.com/microsoft/playwright): Apache-2.0. Downloaded Chromium/WebKit browsers have their own upstream component licences and are not part of this repository.
- [setuptools](https://github.com/pypa/setuptools): MIT.

`uv.lock` and `package-lock.json` identify the resolved packages. Transitive dependencies retain their respective licences. CI actions are external dependencies pinned by commit; they are not copied into this repository.

## Data and research

The bundled network and demand definitions are fictional project examples. No OpenStreetMap data, traffic footage, observed local counts, upstream README copies or downloaded research documents are included. Adding external data later requires separate provenance and licence checks.
