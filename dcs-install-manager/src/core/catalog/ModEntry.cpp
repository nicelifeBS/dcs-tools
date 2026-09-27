#include "ModEntry.h"

#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>

ModEntry::ModEntry(const QString &id, QObject *parent)
    : QObject(parent)
    , m_id(id)
{
}

QString ModEntry::id() const
{
    return m_id;
}

QString ModEntry::name() const
{
    return m_name;
}

void ModEntry::setName(const QString &name)
{
    if (m_name == name)
        return;
    m_name = name;
    emit nameChanged();
}

QString ModEntry::description() const
{
    return m_description;
}

void ModEntry::setDescription(const QString &description)
{
    if (m_description == description)
        return;
    m_description = description;
    emit descriptionChanged();
}

QString ModEntry::module() const
{
    return m_module;
}

void ModEntry::setModule(const QString &module)
{
    if (m_module == module)
        return;
    m_module = module;
    emit moduleChanged();
}

QString ModEntry::category() const
{
    return m_category;
}

void ModEntry::setCategory(const QString &category)
{
    if (m_category == category)
        return;
    m_category = category;
    emit categoryChanged();
}

QStringList ModEntry::tags() const
{
    return m_tags;
}

void ModEntry::setTags(const QStringList &tags)
{
    if (m_tags == tags)
        return;
    m_tags = tags;
    emit tagsChanged();
}

QVariantMap ModEntry::source() const
{
    return m_source;
}

void ModEntry::setSource(const QVariantMap &source)
{
    if (m_source == source)
        return;
    m_source = source;
    emit sourceChanged();
}

QVariantList ModEntry::targets() const
{
    return m_targets;
}

void ModEntry::setTargets(const QVariantList &targets)
{
    if (m_targets == targets)
        return;
    m_targets = targets;
    emit targetsChanged();
}

bool ModEntry::needsReinstallAfterUpdate() const
{
    return m_needsReinstallAfterUpdate;
}

void ModEntry::setNeedsReinstallAfterUpdate(bool needsReinstall)
{
    if (m_needsReinstallAfterUpdate == needsReinstall)
        return;
    m_needsReinstallAfterUpdate = needsReinstall;
    emit needsReinstallAfterUpdateChanged();
}

QString ModEntry::notes() const
{
    return m_notes;
}

void ModEntry::setNotes(const QString &notes)
{
    if (m_notes == notes)
        return;
    m_notes = notes;
    emit notesChanged();
}

QDateTime ModEntry::createdAt() const
{
    return m_createdAt;
}

void ModEntry::setCreatedAt(const QDateTime &createdAt)
{
    m_createdAt = createdAt;
}

QDateTime ModEntry::updatedAt() const
{
    return m_updatedAt;
}

void ModEntry::setUpdatedAt(const QDateTime &updatedAt)
{
    if (m_updatedAt == updatedAt)
        return;
    m_updatedAt = updatedAt;
    emit updatedAtChanged();
}

void ModEntry::applyFields(const QVariantMap &fields)
{
    if (fields.contains(QStringLiteral("name")))
        setName(fields.value(QStringLiteral("name")).toString());
    if (fields.contains(QStringLiteral("description")))
        setDescription(fields.value(QStringLiteral("description")).toString());
    if (fields.contains(QStringLiteral("module")))
        setModule(fields.value(QStringLiteral("module")).toString());
    if (fields.contains(QStringLiteral("category")))
        setCategory(fields.value(QStringLiteral("category")).toString());
    if (fields.contains(QStringLiteral("tags")))
        setTags(fields.value(QStringLiteral("tags")).toStringList());
    if (fields.contains(QStringLiteral("source")))
        setSource(fields.value(QStringLiteral("source")).toMap());
    if (fields.contains(QStringLiteral("targets")))
        setTargets(fields.value(QStringLiteral("targets")).toList());
    if (fields.contains(QStringLiteral("needsReinstallAfterUpdate"))) {
        setNeedsReinstallAfterUpdate(
            fields.value(QStringLiteral("needsReinstallAfterUpdate")).toBool());
    }
    if (fields.contains(QStringLiteral("notes")))
        setNotes(fields.value(QStringLiteral("notes")).toString());
}

QJsonObject ModEntry::toJson() const
{
    QJsonObject json;
    json[QStringLiteral("id")] = m_id;
    json[QStringLiteral("name")] = m_name;
    json[QStringLiteral("description")] = m_description;
    json[QStringLiteral("module")] = m_module;
    json[QStringLiteral("category")] = m_category;
    json[QStringLiteral("tags")] = QJsonArray::fromStringList(m_tags);
    json[QStringLiteral("source")] = QJsonObject::fromVariantMap(m_source);
    json[QStringLiteral("targets")] = QJsonArray::fromVariantList(m_targets);
    json[QStringLiteral("needsReinstallAfterUpdate")] = m_needsReinstallAfterUpdate;
    json[QStringLiteral("notes")] = m_notes;
    json[QStringLiteral("createdAt")] = m_createdAt.toString(Qt::ISODate);
    json[QStringLiteral("updatedAt")] = m_updatedAt.toString(Qt::ISODate);
    return json;
}

ModEntry *ModEntry::fromJson(const QJsonObject &json, QObject *parent)
{
    auto *entry = new ModEntry(json.value(QStringLiteral("id")).toString(), parent);
    entry->setName(json.value(QStringLiteral("name")).toString());
    entry->setDescription(json.value(QStringLiteral("description")).toString());
    entry->setModule(json.value(QStringLiteral("module")).toString());
    entry->setCategory(
        json.value(QStringLiteral("category")).toString(QString::fromLatin1(CategoryMisc)));

    QStringList tags;
    for (const QJsonValue &tag : json.value(QStringLiteral("tags")).toArray())
        tags << tag.toString();
    entry->setTags(tags);

    entry->setSource(json.value(QStringLiteral("source")).toObject().toVariantMap());

    QVariantList targets;
    for (const QJsonValue &target : json.value(QStringLiteral("targets")).toArray())
        targets << target.toObject().toVariantMap();
    entry->setTargets(targets);

    entry->setNeedsReinstallAfterUpdate(
        json.value(QStringLiteral("needsReinstallAfterUpdate")).toBool());
    entry->setNotes(json.value(QStringLiteral("notes")).toString());
    entry->setCreatedAt(
        QDateTime::fromString(json.value(QStringLiteral("createdAt")).toString(), Qt::ISODate));
    entry->setUpdatedAt(
        QDateTime::fromString(json.value(QStringLiteral("updatedAt")).toString(), Qt::ISODate));
    return entry;
}
