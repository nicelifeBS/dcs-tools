#include "ModuleRuleStore.h"

#include "ModuleRule.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QUuid>

ModuleRuleStore::ModuleRuleStore(QObject *parent)
    : QObject(parent)
{
}

bool ModuleRuleStore::load(const QString &filePath)
{
    QFile file(filePath);
    if (!file.exists()) {
        // No module rules file on disk yet: not an error, just nothing to load.
        return true;
    }
    if (!file.open(QIODevice::ReadOnly))
        return false;

    QJsonParseError parseError;
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !doc.isObject())
        return false;

    qDeleteAll(m_moduleRules);
    m_moduleRules.clear();
    m_defaults.clear();

    const QJsonObject root = doc.object();

    const QJsonObject defaultsObject = root.value(QStringLiteral("defaults")).toObject();
    for (auto it = defaultsObject.constBegin(); it != defaultsObject.constEnd(); ++it)
        m_defaults.insert(it.key(), it.value().toObject().toVariantMap());

    const QJsonArray rulesArray = root.value(QStringLiteral("moduleRules")).toArray();
    for (const QJsonValue &value : rulesArray)
        m_moduleRules.append(ModuleRule::fromJson(value.toObject(), this));

    emit rulesChanged();
    return true;
}

bool ModuleRuleStore::save(const QString &filePath) const
{
    const QFileInfo info(filePath);
    if (!info.absoluteDir().exists() && !QDir().mkpath(info.absolutePath()))
        return false;

    QJsonObject defaultsObject;
    for (auto it = m_defaults.constBegin(); it != m_defaults.constEnd(); ++it)
        defaultsObject[it.key()] = QJsonObject::fromVariantMap(it.value().toMap());

    QJsonArray rulesArray;
    for (const ModuleRule *rule : m_moduleRules)
        rulesArray.append(rule->toJson());

    QJsonObject root;
    root[QStringLiteral("schemaVersion")] = 1;
    root[QStringLiteral("defaults")] = defaultsObject;
    root[QStringLiteral("moduleRules")] = rulesArray;

    QFile file(filePath);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;

    file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    return true;
}

const QList<ModuleRule *> &ModuleRuleStore::moduleRules() const
{
    return m_moduleRules;
}

ModuleRule *ModuleRuleStore::findById(const QString &id) const
{
    for (ModuleRule *rule : m_moduleRules) {
        if (rule->id() == id)
            return rule;
    }
    return nullptr;
}

ModuleRule *ModuleRuleStore::addRule(const QVariantMap &fields)
{
    auto *rule = new ModuleRule(QUuid::createUuid().toString(QUuid::WithoutBraces), this);
    rule->applyFields(fields);

    m_moduleRules.append(rule);
    emit rulesChanged();
    return rule;
}

bool ModuleRuleStore::updateRule(const QString &id, const QVariantMap &fields)
{
    ModuleRule *rule = findById(id);
    if (!rule)
        return false;

    rule->applyFields(fields);
    emit rulesChanged();
    return true;
}

bool ModuleRuleStore::removeRule(const QString &id)
{
    ModuleRule *rule = findById(id);
    if (!rule)
        return false;

    m_moduleRules.removeOne(rule);
    rule->deleteLater();
    emit rulesChanged();
    return true;
}

QVariantMap ModuleRuleStore::defaultForCategory(const QString &category) const
{
    return m_defaults.value(category).toMap();
}

void ModuleRuleStore::setDefaultForCategory(const QString &category, const QVariantMap &rule)
{
    m_defaults.insert(category, rule);
    emit rulesChanged();
}
