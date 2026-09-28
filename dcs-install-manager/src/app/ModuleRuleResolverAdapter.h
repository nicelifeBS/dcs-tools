#pragma once

#include <QObject>
#include <QString>
#include <QVariantMap>

class ModuleRuleStore;

// Thin QObject wrapper exposing ModuleRuleResolver::resolve() to QML.
// ModuleRuleResolver itself stays a plain, non-QObject class (it is unit-tested
// directly as such in tst_moduleruleresolver.cpp) - this adapter is the only
// QML-facing surface for it, used by AddEditEntryDialog.qml to auto-resolve a new
// entry's install target from the module rule table.
class ModuleRuleResolverAdapter : public QObject
{
    Q_OBJECT

public:
    explicit ModuleRuleResolverAdapter(ModuleRuleStore *store, QObject *parent = nullptr);

    // Returns a target map ({installLocationKind, dcsVariant, relativePath,
    // fileMappings}), or an empty map if unresolved. See
    // ModuleRuleResolver::resolve() for the exact resolution order.
    Q_INVOKABLE QVariantMap resolve(const QString &module, const QString &category,
                                     const QString &entryName) const;

private:
    ModuleRuleStore *m_store;
};
