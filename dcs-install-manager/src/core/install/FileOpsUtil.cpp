#include "FileOpsUtil.h"

#include <QCryptographicHash>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>

namespace FileOpsUtil {

QStringList listFilesRecursive(const QString &dir)
{
    QStringList result;
    QDir root(dir);
    if (!root.exists())
        return result;

    QDirIterator it(dir, QDir::Files | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
    while (it.hasNext()) {
        it.next();
        result << root.relativeFilePath(it.filePath());
    }
    return result;
}

CopyResult copyFolderRecursive(const QString &sourceDir, const QString &targetDir)
{
    CopyResult result;

    const QStringList relativeFiles = listFilesRecursive(sourceDir);
    const QDir source(sourceDir);
    const QDir target(targetDir);

    for (const QString &relativePath : relativeFiles) {
        const QString sourceFile = source.filePath(relativePath);
        const QString targetFile = target.filePath(relativePath);

        QString error;
        if (!copySingleFile(sourceFile, targetFile, &error)) {
            result.success = false;
            result.errorMessage = error;
            return result;
        }

        result.copiedFiles.append(CopiedFile{relativePath, sourceFile, targetFile});
    }

    result.success = true;
    return result;
}

bool copySingleFile(const QString &sourcePath, const QString &targetPath, QString *errorMessage)
{
    const QFileInfo targetInfo(targetPath);
    QDir targetDir = targetInfo.absoluteDir();
    if (!targetDir.exists() && !targetDir.mkpath(QStringLiteral("."))) {
        if (errorMessage) {
            *errorMessage =
                QStringLiteral("Could not create directory '%1'.").arg(targetDir.absolutePath());
        }
        return false;
    }

    if (QFile::exists(targetPath) && !QFile::remove(targetPath)) {
        if (errorMessage)
            *errorMessage = QStringLiteral("Could not replace existing file '%1'.").arg(targetPath);
        return false;
    }

    if (!QFile::copy(sourcePath, targetPath)) {
        if (errorMessage) {
            *errorMessage =
                QStringLiteral("Could not copy '%1' to '%2'.").arg(sourcePath, targetPath);
        }
        return false;
    }

    return true;
}

QString sha256HashOfFile(const QString &filePath, bool *ok)
{
    QFile file(filePath);
    if (!file.open(QIODevice::ReadOnly)) {
        if (ok)
            *ok = false;
        return QString();
    }

    QCryptographicHash hash(QCryptographicHash::Sha256);
    if (!hash.addData(&file)) {
        if (ok)
            *ok = false;
        return QString();
    }

    if (ok)
        *ok = true;
    return QString::fromLatin1(hash.result().toHex());
}

} // namespace FileOpsUtil
