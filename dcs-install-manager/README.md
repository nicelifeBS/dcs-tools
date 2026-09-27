# DCS Install Manager

A native Windows desktop tool for managing DCS World mods, libraries, and liveries:
install/uninstall to the correct Saved Games or DCS install-dir location, per-module
install-location rules (e.g. liveries that must live in the DCS install dir instead
of Saved Games), and drift detection to catch content wiped out by a DCS update.

Qt 6 + CMake + QML (Windows-only, compiled executable, no Python/runtime packages).

See the full architecture and milestone plan in this repo's session history, or ask
for it to be re-derived from `dcs-install-manager/data/catalog-schema.json` and the
source layout below.

## Status

**Milestone 1 of 7: backend data model & catalog CRUD.** No UI yet — `main.cpp` is a
console smoke test that loads/prints the catalog. Built and unit-tested with CMake +
Qt Test; QML UI, install/uninstall logic, path detection, drift checking, and
packaging land in later milestones.

## Building

Requires Qt 6 (Core, Test) and CMake 3.21+. This project has not yet been build-
verified on an actual Windows/MSVC toolchain — it was developed without one available.

```
cmake -S dcs-install-manager -B dcs-install-manager/build
cmake --build dcs-install-manager/build
ctest --test-dir dcs-install-manager/build
```

## Project layout

```
src/
  main.cpp                        # milestone 1: console smoke test only
  core/catalog/                   # ModEntry, ModCatalog, ModCatalogModel
data/
  catalog-schema.json             # documentation JSON Schema for catalog.json
  default-catalog.json            # empty seed, embedded as a Qt resource
tests/
  tst_modcatalog.cpp              # CRUD + JSON round-trip unit tests
```
