#include "ModuleRuleResolverAdapter.h"

#include "core/rules/ModuleRuleResolver.h"
#include "core/rules/ModuleRuleStore.h"

ModuleRuleResolverAdapter::ModuleRuleResolverAdapter(ModuleRuleStore *store, QObject *parent)
    : QObject(parent)
    , m_store(store)
{
}

QVariantMap ModuleRuleResolverAdapter::resolve(const QString &module, const QString &category,
                                                const QString &entryName) const
{
    const ModuleRuleResolver resolver(m_store);
    return resolver.resolve(module, category, entryName);
}
