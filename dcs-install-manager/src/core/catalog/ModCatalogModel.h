#pragma once

#include <QAbstractListModel>
#include <QObject>

#include "ModCatalog.h"

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
    };
    Q_ENUM(Role)

    explicit ModCatalogModel(ModCatalog *catalog, QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    Q_INVOKABLE QVariant addEntry(const QVariantMap &fields);
    Q_INVOKABLE bool updateEntry(const QString &id, const QVariantMap &fields);
    Q_INVOKABLE bool removeEntry(const QString &id);

private:
    ModCatalog *m_catalog;
};
