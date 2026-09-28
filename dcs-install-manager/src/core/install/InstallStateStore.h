#pragma once

#include <QDateTime>
#include <QList>
#include <QObject>
#include <QString>
#include <optional>

// One file an installation put on disk. This is internal bookkeeping only (never
// user-edited through a form), so a plain struct is the right level of ceremony —
// unlike ModEntry, it doesn't need to be a QObject with Q_PROPERTY per field.
struct InstalledFile
{
    QString targetPath;
    QString sourceHash;
    qint64 sourceSize = 0;
    bool hadPreexistingFile = false;
    QString backupPath; // empty if nothing pre-existed at targetPath
};

// One installed target (a catalog entry's targets[targetIndex]) and every file it put
// on disk under that target's resolved root.
struct InstallationRecord
{
    QString entryId;
    int targetIndex = 0;
    QDateTime installedAt;
    QString resolvedRoot;
    QList<InstalledFile> files;
    // "installed" | "partial". DriftChecker (milestone 6) recomputes further
    // authoritative statuses (missing/changed/source-missing/not-installed) on top of
    // this by comparing live hashes; this field just reflects how the last
    // install/reinstall attempt went.
    QString status;
};

// Owns install_state.json: load/save, and CRUD keyed by (entryId, targetIndex).
// DriftChecker (milestone 6) will iterate allInstallations().
class InstallStateStore : public QObject
{
    Q_OBJECT

public:
    explicit InstallStateStore(QObject *parent = nullptr);

    // Reads filePath into memory, replacing current installations. Returns false (and
    // leaves the store untouched) if the file exists but fails to parse. A missing
    // file is not an error: the store is simply left/started empty. Same semantics as
    // ModCatalog::load.
    bool load(const QString &filePath);

    // Writes the current installations to filePath, creating parent directories as
    // needed.
    bool save(const QString &filePath) const;

    QList<InstallationRecord> installationsForEntry(const QString &entryId) const;
    std::optional<InstallationRecord> installationFor(const QString &entryId, int targetIndex) const;

    // Upserts by (entryId, targetIndex).
    void setInstallation(const InstallationRecord &record);

    bool removeInstallation(const QString &entryId, int targetIndex);

    // Removes every record for entryId. Returns the number of records removed.
    int removeAllForEntry(const QString &entryId);

    const QList<InstallationRecord> &allInstallations() const;

signals:
    // Emitted after any load/set/remove so views (and DriftChecker) can refresh.
    void installStateChanged();

private:
    QList<InstallationRecord> m_installations;
};
