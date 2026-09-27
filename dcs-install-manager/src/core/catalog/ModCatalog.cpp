#include "ModCatalog.h"

#include "ModEntry.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QUuid>

ModCatalog::ModCatalog(QObject *parent)
    : QObject(parent)
{
}

bool ModCatalog::load(const QString &filePath)
{
    QFile file(filePath);
    if (!file.exists()) {
        // No catalog on disk yet: not an error, just nothing to load.
        return true;
    }
    if (!file.open(QIODevice::ReadOnly))
        return false;

    QJsonParseError parseError;
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !doc.isObject())
        return false;

    qDeleteAll(m_entries);
    m_entries.clear();

    const QJsonArray entriesArray = doc.object().value(QStringLiteral("entries")).toArray();
    for (const QJsonValue &value : entriesArray)
        m_entries.append(ModEntry::fromJson(value.toObject(), this));

    emit catalogChanged();
    return true;
}

bool ModCatalog::save(const QString &filePath) const
{
    const QFileInfo info(filePath);
    if (!info.absoluteDir().exists() && !QDir().mkpath(info.absolutePath()))
        return false;

    QJsonArray entriesArray;
    for (const ModEntry *entry : m_entries)
        entriesArray.append(entry->toJson());

    QJsonObject root;
    root[QStringLiteral("schemaVersion")] = 1;
    root[QStringLiteral("entries")] = entriesArray;

    QFile file(filePath);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;

    file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    return true;
}

const QList<ModEntry *> &ModCatalog::entries() const
{
    return m_entries;
}

ModEntry *ModCatalog::findById(const QString &id) const
{
    for (ModEntry *entry : m_entries) {
        if (entry->id() == id)
            return entry;
    }
    return nullptr;
}

ModEntry *ModCatalog::addEntry(const QVariantMap &fields)
{
    auto *entry = new ModEntry(QUuid::createUuid().toString(QUuid::WithoutBraces), this);
    entry->applyFields(fields);
    const QDateTime now = QDateTime::currentDateTimeUtc();
    entry->setCreatedAt(now);
    entry->setUpdatedAt(now);

    m_entries.append(entry);
    emit catalogChanged();
    return entry;
}

bool ModCatalog::updateEntry(const QString &id, const QVariantMap &fields)
{
    ModEntry *entry = findById(id);
    if (!entry)
        return false;

    entry->applyFields(fields);
    entry->setUpdatedAt(QDateTime::currentDateTimeUtc());
    emit catalogChanged();
    return true;
}

bool ModCatalog::removeEntry(const QString &id)
{
    ModEntry *entry = findById(id);
    if (!entry)
        return false;

    m_entries.removeOne(entry);
    entry->deleteLater();
    emit catalogChanged();
    return true;
}
