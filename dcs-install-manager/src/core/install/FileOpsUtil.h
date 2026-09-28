#pragma once

#include <QList>
#include <QString>
#include <QStringList>

// Stateless file-copy/hash helpers used by ModInstaller. Free functions rather than a
// QObject: no state, no signals needed.
namespace FileOpsUtil {

// One file copied by copyFolderRecursive().
struct CopiedFile
{
    QString relativePath; // relative to the source/target roots passed in
    QString sourcePath;
    QString targetPath;
};

// Result of a recursive folder copy. On failure, copiedFiles still lists whatever was
// copied successfully before the failure, so the caller can build install-state
// records for partial progress rather than losing track of it.
struct CopyResult
{
    bool success = false;
    QString errorMessage;
    QList<CopiedFile> copiedFiles;
};

// Lists every file under dir, recursively, as paths relative to dir. Returns an empty
// list if dir doesn't exist or is empty.
QStringList listFilesRecursive(const QString &dir);

// Copies every file under sourceDir into targetDir, preserving relative structure and
// creating parent directories as needed. Stops at the first failure and reports
// whatever was copied so far via CopyResult::copiedFiles, rather than throwing or
// leaving the caller unable to tell what succeeded.
CopyResult copyFolderRecursive(const QString &sourceDir, const QString &targetDir);

// Copies a single file, creating targetPath's parent directory as needed and
// overwriting any existing file at targetPath. Returns false (and, if errorMessage is
// given, a description) on failure.
bool copySingleFile(const QString &sourcePath, const QString &targetPath,
                     QString *errorMessage = nullptr);

// SHA-256 hash of filePath's contents, as a lowercase hex string. Sets *ok (if given)
// to false and returns an empty string if the file can't be opened.
QString sha256HashOfFile(const QString &filePath, bool *ok = nullptr);

} // namespace FileOpsUtil
