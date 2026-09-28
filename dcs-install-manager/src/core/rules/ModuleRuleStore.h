#pragma once

#include <QList>
#include <QObject>
#include <QString>
#include <QVariantMap>

class ModuleRule;

// Owns the module rule table: per-module override rows plus the built-in per-category
// defaults, load/save module_rules.json, and CRUD. This is the single source of truth;
// ModuleRuleModel is the QML-facing read model built on top of it, and
// ModuleRuleResolver reads both the rules and the defaults to resolve a target.
class ModuleRuleStore : public QObject
{
    Q_OBJECT

public:
    explicit ModuleRuleStore(QObject *parent = nullptr);

    // Reads filePath into memory, replacing the current rules and defaults. Returns
    // false (and leaves the store untouched) if the file exists but fails to parse. A
    // missing file is not an error: the store is simply left/started empty.
    bool load(const QString &filePath);

    // Writes the current rules and defaults to filePath, creating parent directories
    // as needed.
    bool save(const QString &filePath) const;

    const QList<ModuleRule *> &moduleRules() const;
    ModuleRule *findById(const QString &id) const;

    ModuleRule *addRule(const QVariantMap &fields);
    bool updateRule(const QString &id, const QVariantMap &fields);
    bool removeRule(const QString &id);

    // The built-in category default (e.g. "livery"), or an empty map if the category
    // has no default. Shaped like { installLocationKind, dcsVariant, pathTemplate }.
    QVariantMap defaultForCategory(const QString &category) const;
    void setDefaultForCategory(const QString &category, const QVariantMap &rule);

signals:
    // Emitted after any add/update/remove/load so views can refresh.
    void rulesChanged();

private:
    QList<ModuleRule *> m_moduleRules;
    QVariantMap m_defaults; // category -> { installLocationKind, dcsVariant, pathTemplate }
};
