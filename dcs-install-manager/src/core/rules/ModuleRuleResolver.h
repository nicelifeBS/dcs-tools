#pragma once

#include <QString>
#include <QVariantMap>

class ModuleRuleStore;

// Pure function-style helper: resolves where a catalog entry's content should install
// by default, given its module/category/name. Used by AddEditEntryDialog to pre-fill
// targets for new entries, and directly reusable by ModInstaller if an entry's own
// targets is ever left empty.
class ModuleRuleResolver
{
public:
    explicit ModuleRuleResolver(const ModuleRuleStore *store);

    // Resolution order: look for a moduleRules row matching (module, category) —
    // module compared case-insensitively — first; if none, fall back to
    // defaults[category]; if neither exists, return an empty QVariantMap (the caller
    // treats this as "unresolved" and asks the user to pick a target manually).
    //
    // On a match, returns a target QVariantMap shaped like one of ModEntry's targets[]
    // entries: { installLocationKind, dcsVariant, relativePath, fileMappings: [] },
    // with the resolved pathTemplate's {module} and {entryName} placeholders
    // substituted with the actual module and entryName passed in.
    QVariantMap resolve(const QString &module, const QString &category,
                         const QString &entryName) const;

private:
    const ModuleRuleStore *m_store;
};
