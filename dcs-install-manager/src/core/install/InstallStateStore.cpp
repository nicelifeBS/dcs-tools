#include "InstallStateStore.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

namespace {

QJsonObject fileToJson(const InstalledFile &file)
{
    QJsonObject json;
    json[QStringLiteral("targetPath")] = file.targetPath;
    json[QStringLiteral("sourceHash")] = file.sourceHash;
    json[QStringLiteral("sourceSize")] = file.sourceSize;
    json[QStringLiteral("hadPreexistingFile")] = file.hadPreexistingFile;
    json[QStringLiteral("backupPath")] = file.backupPath;
    return json;
}

InstalledFile fileFromJson(const QJsonObject &json)
{
    InstalledFile file;
    file.targetPath = json.value(QStringLiteral("targetPath")).toString();
    file.sourceHash = json.value(QStringLiteral("sourceHash")).toString();
    file.sourceSize = static_cast<qint64>(json.value(QStringLiteral("sourceSize")).toDouble());
    file.hadPreexistingFile = json.value(QStringLiteral("hadPreexistingFile")).toBool();
    file.backupPath = json.value(QStringLiteral("backupPath")).toString();
    return file;
}

QJsonObject recordToJson(const InstallationRecord &record)
{
    QJsonObject json;
    json[QStringLiteral("entryId")] = record.entryId;
    json[QStringLiteral("targetIndex")] = record.targetIndex;
    json[QStringLiteral("installedAt")] = record.installedAt.toString(Qt::ISODate);
    json[QStringLiteral("resolvedRoot")] = record.resolvedRoot;
    json[QStringLiteral("status")] = record.status;

    QJsonArray filesArray;
    for (const InstalledFile &file : record.files)
        filesArray.append(fileToJson(file));
    json[QStringLiteral("files")] = filesArray;

    return json;
}

InstallationRecord recordFromJson(const QJsonObject &json)
{
    InstallationRecord record;
    record.entryId = json.value(QStringLiteral("entryId")).toString();
    record.targetIndex = json.value(QStringLiteral("targetIndex")).toInt();
    record.installedAt =
        QDateTime::fromString(json.value(QStringLiteral("installedAt")).toString(), Qt::ISODate);
    record.resolvedRoot = json.value(QStringLiteral("resolvedRoot")).toString();
    record.status = json.value(QStringLiteral("status")).toString();

    for (const QJsonValue &value : json.value(QStringLiteral("files")).toArray())
        record.files.append(fileFromJson(value.toObject()));

    return record;
}

} // namespace

InstallStateStore::InstallStateStore(QObject *parent)
    : QObject(parent)
{
}

bool InstallStateStore::load(const QString &filePath)
{
    QFile file(filePath);
    if (!file.exists()) {
        // No install_state.json on disk yet: not an error, just nothing installed.
        return true;
    }
    if (!file.open(QIODevice::ReadOnly))
        return false;

    QJsonParseError parseError;
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !doc.isObject())
        return false;

    m_installations.clear();

    const QJsonArray installationsArray =
        doc.object().value(QStringLiteral("installations")).toArray();
    for (const QJsonValue &value : installationsArray)
        m_installations.append(recordFromJson(value.toObject()));

    emit installStateChanged();
    return true;
}

bool InstallStateStore::save(const QString &filePath) const
{
    const QFileInfo info(filePath);
    if (!info.absoluteDir().exists() && !QDir().mkpath(info.absolutePath()))
        return false;

    QJsonArray installationsArray;
    for (const InstallationRecord &record : m_installations)
        installationsArray.append(recordToJson(record));

    QJsonObject root;
    root[QStringLiteral("schemaVersion")] = 1;
    root[QStringLiteral("installations")] = installationsArray;

    QFile file(filePath);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;

    file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    return true;
}

QList<InstallationRecord> InstallStateStore::installationsForEntry(const QString &entryId) const
{
    QList<InstallationRecord> result;
    for (const InstallationRecord &record : m_installations) {
        if (record.entryId == entryId)
            result.append(record);
    }
    return result;
}

std::optional<InstallationRecord> InstallStateStore::installationFor(const QString &entryId,
                                                                       int targetIndex) const
{
    for (const InstallationRecord &record : m_installations) {
        if (record.entryId == entryId && record.targetIndex == targetIndex)
            return record;
    }
    return std::nullopt;
}

void InstallStateStore::setInstallation(const InstallationRecord &record)
{
    for (InstallationRecord &existing : m_installations) {
        if (existing.entryId == record.entryId && existing.targetIndex == record.targetIndex) {
            existing = record;
            emit installStateChanged();
            return;
        }
    }

    m_installations.append(record);
    emit installStateChanged();
}

bool InstallStateStore::removeInstallation(const QString &entryId, int targetIndex)
{
    for (int i = 0; i < m_installations.size(); ++i) {
        if (m_installations.at(i).entryId == entryId
            && m_installations.at(i).targetIndex == targetIndex) {
            m_installations.removeAt(i);
            emit installStateChanged();
            return true;
        }
    }
    return false;
}

int InstallStateStore::removeAllForEntry(const QString &entryId)
{
    int removed = 0;
    for (int i = m_installations.size() - 1; i >= 0; --i) {
        if (m_installations.at(i).entryId == entryId) {
            m_installations.removeAt(i);
            ++removed;
        }
    }
    if (removed > 0)
        emit installStateChanged();
    return removed;
}

const QList<InstallationRecord> &InstallStateStore::allInstallations() const
{
    return m_installations;
}
