#include "DcsPathLocator.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <utility>

#ifdef Q_OS_WIN
#include <QSettings>

// windows.h must come first: shlobj.h/knownfolders.h use types that only exist once
// windows.h has defined them (same ordering requirement as DcsProcessGuard.cpp).
#include <windows.h>
#include <shlobj.h>
#include <knownfolders.h>
#endif

DcsPathLocator::DcsPathLocator(CandidateProvider candidateProvider)
    : m_candidateProvider(candidateProvider ? std::move(candidateProvider)
                                             : CandidateProvider(&DcsPathLocator::platformCandidatePaths))
{
}

QList<DcsPathLocator::DetectedInstall> DcsPathLocator::detectInstalls() const
{
    QList<DetectedInstall> results;

    const QStringList candidates = m_candidateProvider ? m_candidateProvider() : QStringList();
    for (const QString &candidate : candidates) {
        if (!isValidInstallRoot(candidate))
            continue;

        DetectedInstall install;
        install.path = candidate;
        install.variant = variantForPath(candidate);
        results.append(install);
    }

    return results;
}

bool DcsPathLocator::isValidInstallRoot(const QString &path)
{
    if (path.isEmpty())
        return false;

    static const QStringList subfolders = {QStringLiteral("bin"), QStringLiteral("bin-mt")};
    for (const QString &subfolder : subfolders) {
        const QString exePath = QDir(path).filePath(subfolder + QStringLiteral("/dcs.exe"));
        if (QFileInfo::exists(exePath))
            return true;
    }
    return false;
}

QString DcsPathLocator::variantForPath(const QString &path)
{
    return path.contains(QStringLiteral("openbeta"), Qt::CaseInsensitive)
               ? QStringLiteral("openbeta")
               : QStringLiteral("stable");
}

QStringList DcsPathLocator::parseSteamLibraryFolders(const QString &vdfContent)
{
    // Valve's KeyValues text format. We only need the "path" values of each numbered
    // library-folder block ("0", "1", ...); a full brace-aware KeyValues parser is
    // overkill since no other block in libraryfolders.vdf uses the literal key
    // "path" (the nested "apps" block maps appid -> size, not "path" -> value), so a
    // straightforward regex scan across the whole content is both correct and robust
    // to formatting/whitespace/tab variations between Steam versions.
    QStringList paths;

    // Captures the quoted value after "path", allowing escaped characters (\" or \\)
    // inside it, same as Valve's own KeyValues escaping.
    static const QRegularExpression pathPattern(
        QStringLiteral(R"re("path"\s*"((?:[^"\\]|\\.)*)")re"));

    QRegularExpressionMatchIterator it = pathPattern.globalMatch(vdfContent);
    while (it.hasNext()) {
        const QRegularExpressionMatch match = it.next();
        QString value = match.captured(1);
        // Un-escape Valve's doubled backslashes (Windows paths are stored as
        // "C:\\\\Program Files..." in the file) and escaped quotes.
        value.replace(QStringLiteral("\\\""), QStringLiteral("\""));
        value.replace(QStringLiteral("\\\\"), QStringLiteral("\\"));
        if (!value.isEmpty())
            paths.append(value);
    }

    return paths;
}

QString DcsPathLocator::detectSavedGamesRoot()
{
#ifdef Q_OS_WIN
    QString result;
    PWSTR rawPath = nullptr;
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_SavedGames, 0, nullptr, &rawPath)) && rawPath) {
        result = QString::fromWCharArray(rawPath);
    }
    if (rawPath)
        CoTaskMemFree(rawPath);
    return result;
#else
    // Not available off Windows; real usage is Windows-only and this genuinely can't
    // be unit-tested here (no SHGetKnownFolderPath). Safe empty-string fallback so
    // callers just treat it as "not detected" rather than crashing or guessing.
    return QString();
#endif
}

QStringList DcsPathLocator::platformCandidatePaths()
{
#ifdef Q_OS_WIN
    QStringList candidates;

    static const QStringList dcsSubdirNames = {
        QStringLiteral("Eagle Dynamics/DCS World"),
        QStringLiteral("Eagle Dynamics/DCS World OpenBeta"),
    };

    // Known Program Files locations (both the 64-bit and, historically, 32-bit
    // Program Files directories - DCS itself is 64-bit only these days, but older
    // installs/third-party launchers have been seen pointing at Program Files (x86)).
    const QStringList programFilesRoots = {
        qEnvironmentVariable("ProgramFiles"),
        qEnvironmentVariable("ProgramFiles(x86)"),
    };
    for (const QString &root : programFilesRoots) {
        if (root.isEmpty())
            continue;
        for (const QString &subdir : dcsSubdirNames)
            candidates << QDir(root).filePath(subdir);
    }

    // Steam library scan: HKCU\Software\Valve\Steam -> SteamPath ->
    // steamapps/libraryfolders.vdf -> every listed library's steamapps/common/<DCS
    // folder name>. Steam's own install location is itself always one library, even
    // if libraryfolders.vdf only lists *additional* ones on some Steam versions, so
    // it's included unconditionally alongside whatever the VDF parse finds.
    QSettings steamRegistry(QStringLiteral("HKEY_CURRENT_USER\\Software\\Valve\\Steam"),
                             QSettings::NativeFormat);
    const QString steamPath = steamRegistry.value(QStringLiteral("SteamPath")).toString();

    if (!steamPath.isEmpty()) {
        QStringList libraryRoots = {steamPath};

        const QString vdfPath = QDir(steamPath).filePath(QStringLiteral("steamapps/libraryfolders.vdf"));
        QFile vdfFile(vdfPath);
        if (vdfFile.open(QIODevice::ReadOnly | QIODevice::Text)) {
            const QString content = QString::fromUtf8(vdfFile.readAll());
            libraryRoots << parseSteamLibraryFolders(content);
        }

        for (const QString &libraryRoot : libraryRoots) {
            if (libraryRoot.isEmpty())
                continue;
            for (const QString &subdir : dcsSubdirNames)
                candidates << QDir(libraryRoot).filePath(QStringLiteral("steamapps/common/") + subdir.section('/', -1));
        }
    }

    candidates.removeDuplicates();
    return candidates;
#else
    // No real Windows filesystem/registry to probe off Windows; real usage is
    // Windows-only. Tests always inject an explicit candidate provider instead of
    // relying on this.
    return QStringList();
#endif
}
