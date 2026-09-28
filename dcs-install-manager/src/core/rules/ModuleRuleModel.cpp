#include "ModuleRuleModel.h"

#include "ModuleRule.h"

ModuleRuleModel::ModuleRuleModel(ModuleRuleStore *store, QObject *parent)
    : QAbstractListModel(parent)
    , m_store(store)
{
    connect(m_store, &ModuleRuleStore::rulesChanged, this, [this]() {
        beginResetModel();
        endResetModel();
    });
}

int ModuleRuleModel::rowCount(const QModelIndex &parent) const
{
    if (parent.isValid())
        return 0;
    return m_store->moduleRules().size();
}

QVariant ModuleRuleModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_store->moduleRules().size())
        return {};

    ModuleRule *rule = m_store->moduleRules().at(index.row());
    switch (role) {
    case IdRole:
        return rule->id();
    case ModuleRole:
        return rule->module();
    case CategoryRole:
        return rule->category();
    case InstallLocationKindRole:
        return rule->installLocationKind();
    case DcsVariantRole:
        return rule->dcsVariant();
    case PathTemplateRole:
        return rule->pathTemplate();
    case NotesRole:
        return rule->notes();
    case RuleObjectRole:
        return QVariant::fromValue(static_cast<QObject *>(rule));
    default:
        return {};
    }
}

QHash<int, QByteArray> ModuleRuleModel::roleNames() const
{
    return {
        {IdRole, "id"},
        {ModuleRole, "module"},
        {CategoryRole, "category"},
        {InstallLocationKindRole, "installLocationKind"},
        {DcsVariantRole, "dcsVariant"},
        {PathTemplateRole, "pathTemplate"},
        {NotesRole, "notes"},
        {RuleObjectRole, "ruleObject"},
    };
}

QVariant ModuleRuleModel::addRule(const QVariantMap &fields)
{
    ModuleRule *rule = m_store->addRule(fields);
    return rule ? rule->id() : QVariant();
}

bool ModuleRuleModel::updateRule(const QString &id, const QVariantMap &fields)
{
    return m_store->updateRule(id, fields);
}

bool ModuleRuleModel::removeRule(const QString &id)
{
    return m_store->removeRule(id);
}
