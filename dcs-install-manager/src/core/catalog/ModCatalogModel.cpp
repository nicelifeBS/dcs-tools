#include "ModCatalogModel.h"

#include "ModEntry.h"

#include "core/install/InstallStateStore.h"

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
    case IsInstalledRole:
        return m_stateStore && !m_stateStore->installationsForEntry(entry->id()).isEmpty();
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
        {IsInstalledRole, "isInstalled"},
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

QVariantMap ModCatalogModel::entryFields(const QString &id) const
{
    ModEntry *entry = m_catalog->findById(id);
    if (!entry)
        return {};

    QVariantMap fields;
    fields[QStringLiteral("id")] = entry->id();
    fields[QStringLiteral("name")] = entry->name();
    fields[QStringLiteral("description")] = entry->description();
    fields[QStringLiteral("module")] = entry->module();
    fields[QStringLiteral("category")] = entry->category();
    fields[QStringLiteral("tags")] = entry->tags();
    fields[QStringLiteral("source")] = entry->source();
    fields[QStringLiteral("targets")] = entry->targets();
    fields[QStringLiteral("needsReinstallAfterUpdate")] = entry->needsReinstallAfterUpdate();
    fields[QStringLiteral("notes")] = entry->notes();
    return fields;
}

void ModCatalogModel::setInstallStateStore(InstallStateStore *stateStore)
{
    if (m_stateStore == stateStore)
        return;

    QObject::disconnect(m_stateStoreConnection);
    m_stateStore = stateStore;

    if (m_stateStore) {
        m_stateStoreConnection =
            connect(m_stateStore, &InstallStateStore::installStateChanged, this, [this]() {
                if (!m_catalog->entries().isEmpty()) {
                    emit dataChanged(index(0), index(m_catalog->entries().size() - 1),
                                      {IsInstalledRole});
                }
            });
    }

    if (!m_catalog->entries().isEmpty())
        emit dataChanged(index(0), index(m_catalog->entries().size() - 1), {IsInstalledRole});
}
