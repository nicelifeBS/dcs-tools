#pragma once

#include <QAbstractListModel>
#include <QMetaObject>
#include <QObject>

#include "ModCatalog.h"

class InstallStateStore;

// QML-facing list adapter over ModCatalog. Uses a full reset on every change since
// catalog edits are infrequent, user-driven actions, not something that needs
// fine-grained row-level animation.
class ModCatalogModel : public QAbstractListModel
{
    Q_OBJECT

public:
    enum Role {
        IdRole = Qt::UserRole + 1,
        NameRole,
        DescriptionRole,
        ModuleRole,
        CategoryRole,
        TagsRole,
        NeedsReinstallRole,
        EntryObjectRole,
        IsInstalledRole,
    };
    Q_ENUM(Role)

    explicit ModCatalogModel(ModCatalog *catalog, QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    Q_INVOKABLE QVariant addEntry(const QVariantMap &fields);
    Q_INVOKABLE bool updateEntry(const QString &id, const QVariantMap &fields);
    Q_INVOKABLE bool removeEntry(const QString &id);

    // Milestone 4 addition: lets QML read every field of one entry (including its
    // targets array) by id, for AddEditEntryDialog's edit mode. Not part of the
    // per-row model roles above since it's needed on demand, not for every row.
    Q_INVOKABLE QVariantMap entryFields(const QString &id) const;

    // Milestone 4 addition: wires the model's IsInstalledRole to InstallStateStore.
    // Optional - a model with no store set just reports "not installed" for every
    // row, so tst_modcatalog.cpp (which never calls this) keeps working unmodified.
    void setInstallStateStore(InstallStateStore *stateStore);

private:
    ModCatalog *m_catalog;
    InstallStateStore *m_stateStore = nullptr;
    QMetaObject::Connection m_stateStoreConnection;
};
