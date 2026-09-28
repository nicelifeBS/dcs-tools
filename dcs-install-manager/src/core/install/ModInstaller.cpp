#include "ModInstaller.h"

#include "FileOpsUtil.h"
#include "InstallStateStore.h"

#include "core/catalog/ModCatalog.h"
#include "core/catalog/ModEntry.h"
#include "core/safety/DcsProcessGuard.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QVariantList>
#include <QVariantMap>

namespace {

// One resolved (source file -> target-relative-to-targetRoot path) pair, built either
// from a whole-folder copy (empty fileMappings) or explicit fileMappings entries.
struct FilePair
{
    QString sourceAbsolute;
    QString targetRelative;
};

QList<FilePair> buildFilePairs(const QString &sourcePath, const QVariantList &fileMappings)
{
    QList<FilePair> pairs;
    const QDir source(sourcePath);

    if (fileMappings.isEmpty()) {
        for (const QString &relativePath : FileOpsUtil::listFilesRecursive(sourcePath))
            pairs.append({source.filePath(relativePath), relativePath});
        return pairs;
    }

    for (const QVariant &mappingVariant : fileMappings) {
        const QVariantMap mapping = mappingVariant.toMap();
        const QString sourceRelative = mapping.value(QStringLiteral("sourceRelative")).toString();
        const QString targetRelative = mapping.value(QStringLiteral("targetRelative")).toString();
        pairs.append({source.filePath(sourceRelative), targetRelative});
    }
    return pairs;
}

} // namespace

ModInstaller::ModInstaller(ModCatalog *catalog, InstallStateStore *stateStore,
                            DcsProcessGuard *processGuard, RootResolver rootResolver,
                            const QString &backupsRootPath, QObject *parent)
    : QObject(parent)
    , m_catalog(catalog)
    , m_stateStore(stateStore)
    , m_processGuard(processGuard)
    , m_rootResolver(std::move(rootResolver))
    , m_backupsRootPath(backupsRootPath)
{
}

ModInstaller::Result ModInstaller::installEntry(const QString &entryId)
{
    if (m_processGuard && m_processGuard->isDcsRunning()) {
        return {false,
                QStringLiteral("Cannot install: DCS is currently running. Close DCS and try again.")};
    }

    ModEntry *entry = m_catalog ? m_catalog->findById(entryId) : nullptr;
    if (!entry)
        return {false, QStringLiteral("No catalog entry found with id '%1'.").arg(entryId)};

    const QString sourcePath = entry->source().value(QStringLiteral("path")).toString();
    if (sourcePath.isEmpty() || !QDir(sourcePath).exists())
        return {false, QStringLiteral("Source folder does not exist: %1").arg(sourcePath)};

    const QVariantList targets = entry->targets();
    if (targets.isEmpty())
        return {false, QStringLiteral("Entry '%1' has no install targets.").arg(entryId)};

    bool anyFailure = false;
    QString failureMessage;

    for (int targetIndex = 0; targetIndex < targets.size(); ++targetIndex) {
        const QVariantMap target = targets.at(targetIndex).toMap();
        const QString installLocationKind =
            target.value(QStringLiteral("installLocationKind")).toString();
        const QString dcsVariant = target.value(QStringLiteral("dcsVariant")).toString();
        const QString relativePath = target.value(QStringLiteral("relativePath")).toString();
        const QVariantList fileMappings = target.value(QStringLiteral("fileMappings")).toList();

        const QString root = m_rootResolver ? m_rootResolver(installLocationKind, dcsVariant) : QString();
        if (root.isEmpty()) {
            anyFailure = true;
            failureMessage = QStringLiteral("Could not resolve install root for target %1 (%2/%3).")
                                  .arg(targetIndex)
                                  .arg(installLocationKind, dcsVariant);
            break;
        }

        const QString targetRoot = QDir(root).filePath(relativePath);
        const QList<FilePair> pairs = buildFilePairs(sourcePath, fileMappings);

        // Existing record for this exact (entryId, targetIndex), consulted so a later
        // reinstall never overwrites an already-recorded backup.
        const std::optional<InstallationRecord> previous =
            m_stateStore->installationFor(entryId, targetIndex);

        InstallationRecord record;
        record.entryId = entryId;
        record.targetIndex = targetIndex;
        record.installedAt = QDateTime::currentDateTimeUtc();
        record.resolvedRoot = root;
        record.status = QStringLiteral("installed");

        bool targetFailed = false;
        for (const FilePair &pair : pairs) {
            const QString targetFile = QDir(targetRoot).filePath(pair.targetRelative);

            // Once we've installed this exact target file before (any record at all,
            // whether or not that record has a backup), the "is there something
            // original here to preserve" decision was already made back then. Trust it
            // verbatim rather than re-deriving it from the current filesystem state -
            // otherwise the tool's own previously-installed copy gets mistaken for "the
            // original" on every subsequent reinstall and spuriously backed up.
            QString backupPath;
            bool hadPreexistingFile = false;
            bool hasPreviousRecordForThisFile = false;

            if (previous) {
                for (const InstalledFile &previousFile : previous->files) {
                    if (previousFile.targetPath == targetFile) {
                        backupPath = previousFile.backupPath;
                        hadPreexistingFile = previousFile.hadPreexistingFile;
                        hasPreviousRecordForThisFile = true;
                        break;
                    }
                }
            }

            if (!hasPreviousRecordForThisFile) {
                hadPreexistingFile = QFile::exists(targetFile);
                if (hadPreexistingFile) {
                    backupPath = QDir(m_backupsRootPath)
                                     .filePath(QStringLiteral("%1/%2/%3")
                                                   .arg(entryId)
                                                   .arg(targetIndex)
                                                   .arg(pair.targetRelative));
                    QString backupError;
                    if (!FileOpsUtil::copySingleFile(targetFile, backupPath, &backupError)) {
                        targetFailed = true;
                        failureMessage = QStringLiteral("Failed to back up existing file '%1': %2")
                                              .arg(targetFile, backupError);
                        break;
                    }
                }
            }

            QString copyError;
            if (!FileOpsUtil::copySingleFile(pair.sourceAbsolute, targetFile, &copyError)) {
                targetFailed = true;
                failureMessage = QStringLiteral("Failed to install '%1': %2").arg(targetFile, copyError);
                break;
            }

            const QString hash = FileOpsUtil::sha256HashOfFile(pair.sourceAbsolute);

            InstalledFile installedFile;
            installedFile.targetPath = targetFile;
            installedFile.sourceHash = hash;
            installedFile.sourceSize = QFileInfo(pair.sourceAbsolute).size();
            installedFile.hadPreexistingFile = hadPreexistingFile;
            installedFile.backupPath = backupPath;
            record.files.append(installedFile);
        }

        if (targetFailed) {
            record.status = QStringLiteral("partial");
            m_stateStore->setInstallation(record);
            anyFailure = true;
            break;
        }

        m_stateStore->setInstallation(record);
    }

    if (anyFailure)
        return {false, failureMessage};

    return {true, QStringLiteral("Installed entry '%1'.").arg(entryId)};
}

ModInstaller::Result ModInstaller::uninstallEntry(const QString &entryId)
{
    if (m_processGuard && m_processGuard->isDcsRunning()) {
        return {false,
                QStringLiteral("Cannot uninstall: DCS is currently running. Close DCS and try again.")};
    }

    const QList<InstallationRecord> records = m_stateStore->installationsForEntry(entryId);
    if (records.isEmpty())
        return {false, QStringLiteral("No installation found for entry '%1'.").arg(entryId)};

    QStringList errors;
    for (const InstallationRecord &record : records) {
        for (const InstalledFile &file : record.files) {
            if (!file.backupPath.isEmpty()) {
                QString error;
                if (!FileOpsUtil::copySingleFile(file.backupPath, file.targetPath, &error)) {
                    errors << error;
                    continue;
                }
                QFile::remove(file.backupPath);
            } else if (QFile::exists(file.targetPath) && !QFile::remove(file.targetPath)) {
                errors << QStringLiteral("Could not remove '%1'.").arg(file.targetPath);
            }
        }
    }

    // An uninstalled entry shouldn't linger as a stale record, even if some individual
    // file operation above failed.
    m_stateStore->removeAllForEntry(entryId);

    if (!errors.isEmpty())
        return {false, errors.join(QStringLiteral("; "))};

    return {true, QStringLiteral("Uninstalled entry '%1'.").arg(entryId)};
}

ModInstaller::ReinstallResult ModInstaller::reinstallMissing()
{
    ReinstallResult result;
    result.success = true;

    if (m_processGuard && m_processGuard->isDcsRunning()) {
        result.success = false;
        result.message =
            QStringLiteral("Cannot reinstall: DCS is currently running. Close DCS and try again.");
        return result;
    }

    QStringList errors;
    const QList<InstallationRecord> records = m_stateStore->allInstallations();

    for (InstallationRecord record : records) {
        ModEntry *entry = m_catalog ? m_catalog->findById(record.entryId) : nullptr;
        const QString sourcePath =
            entry ? entry->source().value(QStringLiteral("path")).toString() : QString();
        const QVariantList targets = entry ? entry->targets() : QVariantList();
        const QVariantMap target = (record.targetIndex >= 0 && record.targetIndex < targets.size())
                                        ? targets.at(record.targetIndex).toMap()
                                        : QVariantMap();
        const QString relativePath = target.value(QStringLiteral("relativePath")).toString();
        const QVariantList fileMappings = target.value(QStringLiteral("fileMappings")).toList();
        const QDir targetRootDir(QDir(record.resolvedRoot).filePath(relativePath));

        bool recordChanged = false;
        for (InstalledFile &file : record.files) {
            if (QFile::exists(file.targetPath))
                continue; // still there, nothing to recover

            if (!entry || sourcePath.isEmpty()) {
                errors << QStringLiteral("Cannot recover '%1': catalog entry or source is unavailable.")
                              .arg(file.targetPath);
                continue;
            }

            const QString targetRelative = targetRootDir.relativeFilePath(file.targetPath);
            QString sourceRelative = targetRelative;

            if (!fileMappings.isEmpty()) {
                bool foundMapping = false;
                for (const QVariant &mappingVariant : fileMappings) {
                    const QVariantMap mapping = mappingVariant.toMap();
                    if (mapping.value(QStringLiteral("targetRelative")).toString() == targetRelative) {
                        sourceRelative = mapping.value(QStringLiteral("sourceRelative")).toString();
                        foundMapping = true;
                        break;
                    }
                }
                if (!foundMapping) {
                    errors << QStringLiteral("Cannot recover '%1': no matching source mapping.")
                                  .arg(file.targetPath);
                    continue;
                }
            }

            const QString sourceFile = QDir(sourcePath).filePath(sourceRelative);
            QString copyError;
            if (!FileOpsUtil::copySingleFile(sourceFile, file.targetPath, &copyError)) {
                errors << QStringLiteral("Failed to recover '%1': %2").arg(file.targetPath, copyError);
                continue;
            }

            file.sourceHash = FileOpsUtil::sha256HashOfFile(sourceFile);
            file.sourceSize = QFileInfo(sourceFile).size();
            recordChanged = true;

            if (!result.recoveredEntryIds.contains(record.entryId))
                result.recoveredEntryIds << record.entryId;
        }

        if (recordChanged)
            m_stateStore->setInstallation(record);
    }

    if (!errors.isEmpty()) {
        result.success = false;
        result.message = errors.join(QStringLiteral("; "));
    } else if (result.recoveredEntryIds.isEmpty()) {
        result.message = QStringLiteral("Nothing to reinstall; all files present.");
    } else {
        result.message = QStringLiteral("Recovered %1 entr%2.")
                              .arg(result.recoveredEntryIds.size())
                              .arg(result.recoveredEntryIds.size() == 1 ? QStringLiteral("y")
                                                                         : QStringLiteral("ies"));
    }

    return result;
}
