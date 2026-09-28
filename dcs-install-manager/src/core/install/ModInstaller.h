#pragma once

#include <QObject>
#include <QString>
#include <QStringList>

#include <functional>

class ModCatalog;
class InstallStateStore;
class DcsProcessGuard;

// Orchestrates install/uninstall/reinstall for catalog entries: resolves each target's
// root via an injected callback, copies files via FileOpsUtil, backs up any
// pre-existing file before its first overwrite (never overwriting an existing backup
// on a later reinstall), and records everything in InstallStateStore.
//
// Deliberately does not depend on DcsPathLocator/SettingsManager (milestone 5): the
// root resolver is the seam that will eventually be backed by that milestone's real
// path-resolution code.
//
// Milestone 4 note: methods stay synchronous, called directly from QML on the main
// thread, rather than moved to QtConcurrent::run as originally sketched. ModCatalog
// and InstallStateStore have no locking or thread-affinity handling, so running these
// on a worker thread while QML reads them on the main thread would need real
// thread-safety work first. For a local single-user tool copying a handful of small
// files at a time, a brief synchronous call is an acceptable trade-off for now.
class ModInstaller : public QObject
{
    Q_OBJECT

public:
    // Maps (installLocationKind, dcsVariant) to an absolute directory to install
    // under, or an empty string if unresolvable (treated as a failure for that
    // target). In production this will eventually be supplied by milestone 5's
    // DcsPathLocator/SettingsManager; tests inject a lambda returning fixed temp dirs.
    using RootResolver =
        std::function<QString(const QString &installLocationKind, const QString &dcsVariant)>;

    struct Result
    {
        bool success = false;
        QString message;
    };

    struct ReinstallResult
    {
        bool success = false;
        QString message;
        QStringList recoveredEntryIds; // entryIds that had at least one file recovered
    };

    explicit ModInstaller(ModCatalog *catalog, InstallStateStore *stateStore,
                          DcsProcessGuard *processGuard, RootResolver rootResolver,
                          const QString &backupsRootPath, QObject *parent = nullptr);

    // Refuses immediately (no filesystem changes at all) if processGuard reports DCS
    // running. Otherwise installs every target of the entry, backing up any
    // pre-existing target file before first overwrite. On any per-file failure, stops,
    // persists whatever succeeded so far (status "partial" on the affected target) and
    // returns a failure result.
    //
    // Q_INVOKABLE (milestone 4): callable from QML on the main thread. QML itself goes
    // through ModInstallerAdapter (src/app/), which converts this struct into a
    // QVariantMap so its fields are readable from QML - see that adapter's header for
    // why. See the class comment above for why this stays synchronous rather than
    // QtConcurrent.
    Q_INVOKABLE Result installEntry(const QString &entryId);

    // Refuses if processGuard reports DCS running. Restores each installed file's
    // backup (and removes the backup) where one exists, or deletes the target file
    // where nothing pre-existed, then removes the entry's installation record(s)
    // entirely.
    Q_INVOKABLE Result uninstallEntry(const QString &entryId);

    // Refuses if processGuard reports DCS running. Re-copies any installed file that's
    // gone missing from disk (e.g. wiped by a DCS update) from the catalog entry's
    // source, without creating a new backup, and refreshes its recorded hash/size.
    Q_INVOKABLE ReinstallResult reinstallMissing();

private:
    ModCatalog *m_catalog;
    InstallStateStore *m_stateStore;
    DcsProcessGuard *m_processGuard;
    RootResolver m_rootResolver;
    QString m_backupsRootPath;
};
