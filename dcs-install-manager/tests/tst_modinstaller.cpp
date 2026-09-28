#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QTest>

#include "core/catalog/ModCatalog.h"
#include "core/catalog/ModEntry.h"
#include "core/install/FileOpsUtil.h"
#include "core/install/InstallStateStore.h"
#include "core/install/ModInstaller.h"
#include "core/safety/DcsProcessGuard.h"

namespace {

bool writeFile(const QString &path, const QByteArray &content)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;
    file.write(content);
    return true;
}

QByteArray readFile(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return QByteArray();
    return file.readAll();
}

} // namespace

class tst_ModInstaller : public QObject
{
    Q_OBJECT

private slots:
    void installEntry_wholeFolderCopy_recordsInstalledStatusAndHashes();
    void installEntry_backsUpPreexistingFileBeforeOverwrite();
    void installEntry_secondInstall_doesNotOverwriteExistingBackup();
    void uninstallEntry_withPreexistingFile_restoresOriginalContent();
    void uninstallEntry_withoutPreexistingFile_deletesFileAndRemovesRecord();
    void reinstallMissing_recopiesDeletedFile();
    void installEntry_refusesWhenDcsRunning_noFilesystemChanges();
    void installEntry_partialFailure_recordsPartialStatus();
    void installEntry_reinstallWithoutOriginalPreexisting_doesNotBackUpOwnPreviousCopy();
};

void tst_ModInstaller::installEntry_wholeFolderCopy_recordsInstalledStatusAndHashes()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "top level content"));
    QVERIFY(writeFile(sourceDir.filePath("nested/file2.txt"), "nested content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    const ModInstaller::Result result = installer.installEntry(entry->id());
    QVERIFY(result.success);

    const QString targetFile1 = targetRootDir.filePath("SomeMod/file1.txt");
    const QString targetFile2 = targetRootDir.filePath("SomeMod/nested/file2.txt");
    QVERIFY(QFile::exists(targetFile1));
    QVERIFY(QFile::exists(targetFile2));
    QCOMPARE(readFile(targetFile1), QByteArray("top level content"));
    QCOMPARE(readFile(targetFile2), QByteArray("nested content"));

    const std::optional<InstallationRecord> record = stateStore.installationFor(entry->id(), 0);
    QVERIFY(record.has_value());
    QCOMPARE(record->status, QStringLiteral("installed"));
    QCOMPARE(record->files.size(), 2);

    for (const InstalledFile &file : record->files) {
        QVERIFY(!file.hadPreexistingFile);
        QVERIFY(file.backupPath.isEmpty());
        bool ok = false;
        const QString expectedHash =
            FileOpsUtil::sha256HashOfFile(file.targetPath == targetFile1 ? sourceDir.filePath("file1.txt")
                                                                          : sourceDir.filePath("nested/file2.txt"),
                                           &ok);
        QVERIFY(ok);
        QCOMPARE(file.sourceHash, expectedHash);
    }
}

void tst_ModInstaller::installEntry_backsUpPreexistingFileBeforeOverwrite()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "new mod content"));

    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(writeFile(targetFile, "original preexisting content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    const ModInstaller::Result result = installer.installEntry(entry->id());
    QVERIFY(result.success);

    QCOMPARE(readFile(targetFile), QByteArray("new mod content"));

    const std::optional<InstallationRecord> record = stateStore.installationFor(entry->id(), 0);
    QVERIFY(record.has_value());
    QCOMPARE(record->files.size(), 1);
    const InstalledFile &installedFile = record->files.first();
    QVERIFY(installedFile.hadPreexistingFile);
    QVERIFY(!installedFile.backupPath.isEmpty());
    QVERIFY(QFile::exists(installedFile.backupPath));
    QCOMPARE(readFile(installedFile.backupPath), QByteArray("original preexisting content"));
}

void tst_ModInstaller::installEntry_secondInstall_doesNotOverwriteExistingBackup()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "source v1"));

    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(writeFile(targetFile, "the true original"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    QVERIFY(installer.installEntry(entry->id()).success);

    const std::optional<InstallationRecord> firstRecord = stateStore.installationFor(entry->id(), 0);
    QVERIFY(firstRecord.has_value());
    const QString backupPath = firstRecord->files.first().backupPath;
    QVERIFY(!backupPath.isEmpty());

    // Simulate the library being updated, then re-install the same entry.
    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "source v2"));
    QVERIFY(installer.installEntry(entry->id()).success);

    // Backup must still hold the true original, not "source v1" or the first backup
    // path's content changing.
    QCOMPARE(readFile(backupPath), QByteArray("the true original"));
    QCOMPARE(readFile(targetFile), QByteArray("source v2"));

    const std::optional<InstallationRecord> secondRecord = stateStore.installationFor(entry->id(), 0);
    QVERIFY(secondRecord.has_value());
    QCOMPARE(secondRecord->files.first().backupPath, backupPath);
}

void tst_ModInstaller::uninstallEntry_withPreexistingFile_restoresOriginalContent()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "mod content"));
    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(writeFile(targetFile, "original content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    QVERIFY(installer.installEntry(entry->id()).success);
    const QString backupPath = stateStore.installationFor(entry->id(), 0)->files.first().backupPath;

    const ModInstaller::Result result = installer.uninstallEntry(entry->id());
    QVERIFY(result.success);

    QCOMPARE(readFile(targetFile), QByteArray("original content"));
    QVERIFY(!QFile::exists(backupPath));
    QVERIFY(!stateStore.installationFor(entry->id(), 0).has_value());
}

void tst_ModInstaller::uninstallEntry_withoutPreexistingFile_deletesFileAndRemovesRecord()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "mod content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    QVERIFY(installer.installEntry(entry->id()).success);
    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(QFile::exists(targetFile));

    const ModInstaller::Result result = installer.uninstallEntry(entry->id());
    QVERIFY(result.success);

    QVERIFY(!QFile::exists(targetFile));
    QVERIFY(!stateStore.installationFor(entry->id(), 0).has_value());
}

void tst_ModInstaller::reinstallMissing_recopiesDeletedFile()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "mod content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    QVERIFY(installer.installEntry(entry->id()).success);
    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(QFile::exists(targetFile));

    // Simulate a DCS update wiping the installed file.
    QVERIFY(QFile::remove(targetFile));
    QVERIFY(!QFile::exists(targetFile));

    const ModInstaller::ReinstallResult result = installer.reinstallMissing();
    QVERIFY(result.success);
    QVERIFY(result.recoveredEntryIds.contains(entry->id()));

    QVERIFY(QFile::exists(targetFile));
    QCOMPARE(readFile(targetFile), QByteArray("mod content"));

    bool ok = false;
    const QString expectedHash = FileOpsUtil::sha256HashOfFile(sourceDir.filePath("file1.txt"), &ok);
    QVERIFY(ok);
    QCOMPARE(stateStore.installationFor(entry->id(), 0)->files.first().sourceHash, expectedHash);
}

void tst_ModInstaller::installEntry_refusesWhenDcsRunning_noFilesystemChanges()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "mod content"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{QStringLiteral("DCS.exe")}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    const ModInstaller::Result result = installer.installEntry(entry->id());
    QVERIFY(!result.success);
    QVERIFY(!result.message.isEmpty());

    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QVERIFY(!QFile::exists(targetFile));
    QVERIFY(!stateStore.installationFor(entry->id(), 0).has_value());
}

void tst_ModInstaller::installEntry_partialFailure_recordsPartialStatus()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "mod content"));

    // Put a plain FILE where the installer will need to create a DIRECTORY
    // (targetRoot/BlockedDir), so QDir::mkpath fails regardless of the running user's
    // privileges (tests likely run as root in this sandbox, so a chmod-based
    // permission failure wouldn't actually fail).
    const QString blockedPath = targetRootDir.filePath("BlockedDir");
    QVERIFY(writeFile(blockedPath, "I am a file, not a directory"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "BlockedDir"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    const ModInstaller::Result result = installer.installEntry(entry->id());
    QVERIFY(!result.success);
    QVERIFY(!result.message.isEmpty());

    const std::optional<InstallationRecord> record = stateStore.installationFor(entry->id(), 0);
    QVERIFY(record.has_value());
    QCOMPARE(record->status, QStringLiteral("partial"));
}

void tst_ModInstaller::installEntry_reinstallWithoutOriginalPreexisting_doesNotBackUpOwnPreviousCopy()
{
    QTemporaryDir sourceDir;
    QTemporaryDir targetRootDir;
    QTemporaryDir backupsDir;
    QVERIFY(sourceDir.isValid() && targetRootDir.isValid() && backupsDir.isValid());

    // Nothing pre-exists at the target the first time.
    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "source v1"));

    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Test Library"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryAircraftLibrary},
        {"source", QVariantMap{{"kind", "folder"}, {"path", sourceDir.path()}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "any"},
             {"relativePath", "SomeMod"},
             {"fileMappings", QVariantList{}},
         }}},
    });

    InstallStateStore stateStore;
    DcsProcessGuard processGuard([]() { return QStringList{}; });
    ModInstaller installer(
        &catalog, &stateStore, &processGuard,
        [&](const QString &, const QString &) { return targetRootDir.path(); }, backupsDir.path());

    QVERIFY(installer.installEntry(entry->id()).success);
    const std::optional<InstallationRecord> firstRecord = stateStore.installationFor(entry->id(), 0);
    QVERIFY(firstRecord.has_value());
    QVERIFY(!firstRecord->files.first().hadPreexistingFile);
    QVERIFY(firstRecord->files.first().backupPath.isEmpty());

    // Reinstall the same entry (e.g. the library file changed) with nothing external
    // having touched the target in between. Since nothing pre-existed the FIRST time,
    // the tool's own previously-installed copy must not be mistaken for "the original"
    // and backed up on this second install.
    QVERIFY(writeFile(sourceDir.filePath("file1.txt"), "source v2"));
    QVERIFY(installer.installEntry(entry->id()).success);

    const std::optional<InstallationRecord> secondRecord = stateStore.installationFor(entry->id(), 0);
    QVERIFY(secondRecord.has_value());
    QVERIFY(!secondRecord->files.first().hadPreexistingFile);
    QVERIFY(secondRecord->files.first().backupPath.isEmpty());

    const QString targetFile = targetRootDir.filePath("SomeMod/file1.txt");
    QCOMPARE(readFile(targetFile), QByteArray("source v2"));
}

QTEST_APPLESS_MAIN(tst_ModInstaller)
#include "tst_modinstaller.moc"
