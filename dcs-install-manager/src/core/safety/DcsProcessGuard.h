#pragma once

#include <QStringList>

#include <functional>

// Is the main DCS game process currently running? Checked before every
// install/uninstall/reinstall operation, since the game can hold its own files open.
//
// The real process enumeration is Windows-only (CreateToolhelp32Snapshot). To keep
// this class unit-testable on any platform, the process list itself is supplied by an
// injectable provider rather than read directly from the OS in isDcsRunning() —
// production code uses the default (real) provider, tests inject a fake one.
class DcsProcessGuard
{
public:
    using ProcessListProvider = std::function<QStringList()>;

    // The main DCS game executable's expected process name. Flagged in the plan as
    // unverified against a real install — kept as a single named constant so it's the
    // obvious point of change once confirmed. Deliberately does NOT match the separate
    // DCS Updater/Launcher process names, which are fine to have open.
    static constexpr const char *DcsExecutableName = "DCS.exe";

    // processListProvider defaults to the real platform process enumeration (Windows
    // only; returns an empty list on any other platform, so the guard is a harmless
    // no-op there). Pass a fake provider (e.g. returning {"DCS.exe"}) to test without
    // touching any OS API.
    explicit DcsProcessGuard(ProcessListProvider processListProvider = nullptr);

    // Case-insensitive match of DcsExecutableName against the current process list.
    bool isDcsRunning() const;

private:
    static QStringList platformProcessList();

    ProcessListProvider m_processListProvider;
};
