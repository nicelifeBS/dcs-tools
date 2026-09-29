#pragma once

#include <QList>
#include <QString>
#include <QStringList>

#include <functional>

// Heuristic DCS Stable/Open Beta install-dir and Saved Games auto-detection (see the
// plan's "DCS path auto-detection (Windows)" section). There is no stable Eagle
// Dynamics registry key for the install path, so this is always surfaced to the user
// as a confirm/override list (PathSetupForm.qml), never silently applied.
//
// Same testability pattern as DcsProcessGuard: the real candidate-path enumeration
// (known Program Files locations plus a Steam library scan via the
// HKCU\Software\Valve\Steam registry key) is Windows-only and lives behind
// platformCandidatePaths(), guarded by #ifdef Q_OS_WIN with an empty-list fallback
// elsewhere. detectInstalls() itself takes an injectable candidate provider so it can
// be unit-tested end-to-end on any platform against fake temp-directory "installs",
// without touching the OS at all.
class DcsPathLocator
{
public:
    struct DetectedInstall
    {
        QString variant; // "stable" | "openbeta" - tagged, not user-confirmed.
        QString path;
    };

    using CandidateProvider = std::function<QStringList()>;

    // candidateProvider defaults to the real platform candidate enumeration (Windows
    // only; returns an empty list on any other platform). Pass a fake provider (e.g.
    // returning fixed temp-dir paths) to test detectInstalls() without touching the OS.
    explicit DcsPathLocator(CandidateProvider candidateProvider = nullptr);

    // Filters the provider's candidate paths down to the ones that actually look like
    // a DCS install (see isValidInstallRoot), tagging each survivor's variant (see
    // variantForPath). Order follows the provider's own order; no further sorting.
    QList<DetectedInstall> detectInstalls() const;

    // Saved Games root via SHGetKnownFolderPath(FOLDERID_SavedGames) on Windows (this
    // correctly follows OneDrive/junction relocation, unlike a hardcoded path) - empty
    // string elsewhere or on any failure. Not unit-testable here; guarded + a safe
    // non-crashing fallback is the whole of what's verifiable off real Windows.
    static QString detectSavedGamesRoot();

    // True if `path` contains a bin/dcs.exe or bin-mt/dcs.exe (DCS ships the same exe
    // name in either subfolder depending on single/multi-threaded mode - see
    // DcsProcessGuard's DcsExecutableName comment for the same caveat carried here).
    static bool isValidInstallRoot(const QString &path);

    // Simple heuristic: "openbeta" appears (case-insensitively) anywhere in the path,
    // else "stable". Good enough for the typical "DCS World OpenBeta" folder naming;
    // never authoritative, always confirmable/overridable by the user.
    static QString variantForPath(const QString &path);

    // Pure parser for Steam's libraryfolders.vdf content (Valve's KeyValues text
    // format) - returns every "path" value found, backslashes un-escaped. Exposed as a
    // free/static function specifically so it can be unit-tested against sample VDF
    // content without any real Steam installation.
    static QStringList parseSteamLibraryFolders(const QString &vdfContent);

private:
    static QStringList platformCandidatePaths();

    CandidateProvider m_candidateProvider;
};
