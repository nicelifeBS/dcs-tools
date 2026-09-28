#pragma once

#include <QAbstractListModel>
#include <QObject>

#include "ModuleRuleStore.h"

// QML-facing list adapter over ModuleRuleStore's moduleRules (the per-category
// defaults are not part of this model; ModuleRulesView shows them separately as
// read-only rows). Uses a full reset on every change since rule edits are infrequent,
// user-driven actions, not something that needs fine-grained row-level animation.
class ModuleRuleModel : public QAbstractListModel
{
    Q_OBJECT

public:
    enum Role {
        IdRole = Qt::UserRole + 1,
        ModuleRole,
        CategoryRole,
        InstallLocationKindRole,
        DcsVariantRole,
        PathTemplateRole,
        NotesRole,
        RuleObjectRole,
    };
    Q_ENUM(Role)

    explicit ModuleRuleModel(ModuleRuleStore *store, QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    Q_INVOKABLE QVariant addRule(const QVariantMap &fields);
    Q_INVOKABLE bool updateRule(const QString &id, const QVariantMap &fields);
    Q_INVOKABLE bool removeRule(const QString &id);

private:
    ModuleRuleStore *m_store;
};
