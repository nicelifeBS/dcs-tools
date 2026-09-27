#include "ModCatalogModel.h"

#include "ModEntry.h"

ModCatalogModel::ModCatalogModel(ModCatalog *catalog, QObject *parent)
    : QAbstractListModel(parent)
    , m_catalog(catalog)
{
    connect(m_catalog, &ModCatalog::catalogChanged, this, [this]() {
        beginResetModel();
        endResetModel();
    });
}

int ModCatalogModel::rowCount(const QModelIndex &parent) const
{
    if (parent.isValid())
        return 0;
    return m_catalog->entries().size();
}

QVariant ModCatalogModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_catalog->entries().size())
        return {};

    ModEntry *entry = m_catalog->entries().at(index.row());
    switch (role) {
    case IdRole:
        return entry->id();
    case NameRole:
        return entry->name();
    case DescriptionRole:
        return entry->description();
    case ModuleRole:
        return entry->module();
    case CategoryRole:
        return entry->category();
    case TagsRole:
        return entry->tags();
    case NeedsReinstallRole:
        return entry->needsReinstallAfterUpdate();
    case EntryObjectRole:
        return QVariant::fromValue(static_cast<QObject *>(entry));
    default:
        return {};
    }
}

QHash<int, QByteArray> ModCatalogModel::roleNames() const
{
    return {
        {IdRole, "id"},
        {NameRole, "name"},
        {DescriptionRole, "description"},
        {ModuleRole, "module"},
        {CategoryRole, "category"},
        {TagsRole, "tags"},
        {NeedsReinstallRole, "needsReinstallAfterUpdate"},
        {EntryObjectRole, "entryObject"},
    };
}

QVariant ModCatalogModel::addEntry(const QVariantMap &fields)
{
    ModEntry *entry = m_catalog->addEntry(fields);
    return entry ? entry->id() : QVariant();
}

bool ModCatalogModel::updateEntry(const QString &id, const QVariantMap &fields)
{
    return m_catalog->updateEntry(id, fields);
}

bool ModCatalogModel::removeEntry(const QString &id)
{
    return m_catalog->removeEntry(id);
}
