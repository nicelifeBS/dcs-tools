#include "ModuleRuleResolver.h"

#include "ModuleRule.h"
#include "ModuleRuleStore.h"

ModuleRuleResolver::ModuleRuleResolver(const ModuleRuleStore *store)
    : m_store(store)
{
}

QVariantMap ModuleRuleResolver::resolve(const QString &module, const QString &category,
                                         const QString &entryName) const
{
    QString installLocationKind;
    QString dcsVariant;
    QString pathTemplate;
    bool resolved = false;

    for (const ModuleRule *rule : m_store->moduleRules()) {
        if (rule->category() != category)
            continue;
        if (rule->module().compare(module, Qt::CaseInsensitive) != 0)
            continue;

        installLocationKind = rule->installLocationKind();
        dcsVariant = rule->dcsVariant();
        pathTemplate = rule->pathTemplate();
        resolved = true;
        break;
    }

    if (!resolved) {
        const QVariantMap categoryDefault = m_store->defaultForCategory(category);
        if (categoryDefault.isEmpty())
            return {};

        installLocationKind = categoryDefault.value(QStringLiteral("installLocationKind")).toString();
        dcsVariant = categoryDefault.value(QStringLiteral("dcsVariant")).toString();
        pathTemplate = categoryDefault.value(QStringLiteral("pathTemplate")).toString();
        resolved = true;
    }

    QString relativePath = pathTemplate;
    relativePath.replace(QStringLiteral("{module}"), module);
    relativePath.replace(QStringLiteral("{entryName}"), entryName);

    QVariantMap target;
    target[QStringLiteral("installLocationKind")] = installLocationKind;
    target[QStringLiteral("dcsVariant")] = dcsVariant;
    target[QStringLiteral("relativePath")] = relativePath;
    target[QStringLiteral("fileMappings")] = QVariantList();
    return target;
}
